#!/usr/bin/env python3
# coding: utf-8
# pyright: reportMissingImports=false, reportGeneralTypeIssues=false
# pyright: reportMissingModuleSource=false, reportAttributeAccessIssue=false

"""Gitlab Jobs Logs Downloader"""

import logging
import os
import sys
import time
from datetime import datetime

import pytz
import requests
from slugify import slugify

GITLAB_JOBS_LOGS_DOWNLOADER_LOGLEVEL = os.environ.get(
    "GITLAB_JOBS_LOGS_DOWNLOADER_LOGLEVEL", "INFO"
).upper()
GITLAB_JOBS_LOGS_DOWNLOADER_DIRECTORY = os.environ.get(
    "GITLAB_JOBS_LOGS_DOWNLOADER_DIRECTORY", "/tmp"  # nosec B108
)
GITLAB_JOBS_LOGS_DOWNLOADER_TZ = os.environ.get("TZ", "Europe/Paris")
GITLAB_JOBS_LOGS_DOWNLOADER_FILENAME_DELIMITER = os.environ.get(
    "GITLAB_JOBS_LOGS_DOWNLOADER_FILENAME_DELIMITER", "#"
)

try:
    GITLAB_JOBS_LOGS_DOWNLOADER_JOB_CHECK_INTERVAL_SECONDS = int(
        os.environ.get("GITLAB_JOBS_LOGS_DOWNLOADER_JOB_CHECK_INTERVAL_SECONDS", "10")
    )
except ValueError:
    logging.error(
        "GITLAB_JOBS_LOGS_DOWNLOADER_JOB_CHECK_INTERVAL_SECONDS must be int !"
    )
    os._exit(1)

try:
    GITLAB_JOBS_LOGS_DOWNLOADER_RUNNING_JOB_TIMEOUT_SECONDS = int(
        os.environ.get("GITLAB_JOBS_LOGS_DOWNLOADER_RUNNING_JOB_TIMEOUT_SECONDS", "60")
    )
except ValueError:
    logging.error(
        "GITLAB_JOBS_LOGS_DOWNLOADER_RUNNING_JOB_TIMEOUT_SECONDS must be int !"
    )
    os._exit(1)

try:
    GITLAB_JOBS_LOGS_DOWNLOADER_END_JOB_TIMEOUT_SECONDS = int(
        os.environ.get("GITLAB_JOBS_LOGS_DOWNLOADER_END_JOB_TIMEOUT_SECONDS", "120")
    )
except ValueError:
    logging.error("GITLAB_JOBS_LOGS_DOWNLOADER_END_JOB_TIMEOUT_SECONDS must be int !")
    os._exit(1)

# CI_API_TOKEN must be the last element of MANDATORY_ENV_VARS (hide secret)
MANDATORY_ENV_VARS = [
    "CI_PROJECT_ID",
    "CI_PIPELINE_ID",
    "CI_API_V4_URL",
    "CI_API_TOKEN",
]

# Logging Configuration
try:
    pytz.timezone(GITLAB_JOBS_LOGS_DOWNLOADER_TZ)
    logging.Formatter.converter = lambda *args: datetime.now(
        tz=pytz.timezone(GITLAB_JOBS_LOGS_DOWNLOADER_TZ)
    ).timetuple()
    logging.basicConfig(
        stream=sys.stdout,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%d/%m/%Y %H:%M:%S",
        level=GITLAB_JOBS_LOGS_DOWNLOADER_LOGLEVEL,
    )
except pytz.exceptions.UnknownTimeZoneError:
    logging.Formatter.converter = lambda *args: datetime.now(
        tz=pytz.timezone("Europe/Paris")
    ).timetuple()
    logging.basicConfig(
        stream=sys.stdout,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%d/%m/%Y %H:%M:%S",
        level="INFO",
    )
    logging.error("TZ invalid : %s !", GITLAB_JOBS_LOGS_DOWNLOADER_LOGLEVEL)
    os._exit(1)
except ValueError:
    logging.basicConfig(
        stream=sys.stdout,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%d/%m/%Y %H:%M:%S",
        level="INFO",
    )
    logging.error("GITLAB_JOBS_LOGS_DOWNLOADER_LOGLEVEL invalid !")
    os._exit(1)

# Check Mandatory Environment Variable
for var in MANDATORY_ENV_VARS:
    if var not in os.environ:
        logging.critical("%s environment variable must be set !", var)
        os._exit(1)

CI_API_TOKEN = os.environ.get("CI_API_TOKEN")
CI_API_V4_URL = os.environ.get("CI_API_V4_URL")
CI_PROJECT_ID = os.environ.get("CI_PROJECT_ID")
CI_PIPELINE_ID = os.environ.get("CI_PIPELINE_ID")


class GitlabJobsLogsDownloader:
    """Gitlab Jobs Logs Downloader"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers = {"PRIVATE-TOKEN": CI_API_TOKEN}
        self.project = self.get_project()
        self.project_name = self.project.json()["name"]
        logging.info("GITLAB_PROJECT_NAME=%s", self.project.json()["name"])
        self.pipeline_jobs = self.get_pipeline_jobs()
        logging.info("RETRIEVING %s JOBS", len(self.pipeline_jobs))
        self.download_pipeline_jobs_logs()

    def get_project(self):
        """Retrieve Gitlab Project"""
        project = self.session.get(f"{CI_API_V4_URL}/projects/{CI_PROJECT_ID}")
        if project.status_code != 200:
            logging.error("UNKNOWN GITLAB PROJECT ID %s !", CI_PROJECT_ID)
            os._exit(1)
        logging.debug("PROJECT=%s", project.json())
        return project

    def get_pipeline_jobs(self):
        """Retrieve Gitlab Pipeline Jobs"""
        url = (
            f"{CI_API_V4_URL}/projects/{CI_PROJECT_ID}/pipelines/{CI_PIPELINE_ID}/jobs"
        )
        pipeline_jobs = []
        while True:
            response = self.session.get(url)
            if response.status_code != 200:
                logging.error(
                    "UNKNOWN GITLAB PIPELINE ID %s FOR %s",
                    CI_PIPELINE_ID,
                    self.project_name,
                )
                os._exit(1)
            pipeline_jobs.extend(response.json())
            link_header = response.headers.get("Link")
            if link_header:
                next_page_url = self.extract_next_page_url(link_header)
                if next_page_url:
                    url = next_page_url
                else:
                    break
            else:
                break
        logging.debug("JOBS=%s", pipeline_jobs)
        return sorted(pipeline_jobs, key=lambda x: x["id"])

    @staticmethod
    def extract_next_page_url(link_header):
        """Extract Next Page URL"""
        links = link_header.split(", ")
        for link in links:
            url, rel = link.split("; ")
            url = url.strip("<>")
            rel = rel.split("=")[1].strip('"')
            if rel == "next":
                return url
        return None

    def get_job(self, job_id):
        """Get Job"""
        response = self.session.get(
            f"{CI_API_V4_URL}/projects/{CI_PROJECT_ID}/jobs/{job_id}"
        )
        if response.status_code != 200:
            return {}
        logging.debug("JOB=%s", response.json())
        return response.json()

    def check_running_timeout(self, job_name, job_stage, job_id, job_status):
        """Check Running Timeout"""
        init = datetime.now()
        while job_status == "running":
            if (
                datetime.now() - init
            ).total_seconds() >= GITLAB_JOBS_LOGS_DOWNLOADER_RUNNING_JOB_TIMEOUT_SECONDS:
                logging.error(
                    'JOB="%s" STAGE="%s" PROJECT="%s" RUNNING JOB TIMEOUT WAS REACHED !"',
                    job_name,
                    job_stage,
                    self.project_name,
                )
                return True
            logging.info(
                'JOB="%s" STAGE="%s" PROJECT="%s" STILL RUNNING !"',
                job_name,
                job_stage,
                self.project_name,
            )
            time.sleep(GITLAB_JOBS_LOGS_DOWNLOADER_RUNNING_JOB_TIMEOUT_SECONDS)
            job_status = self.get_job(job_id)["status"]
        return False

    def check_end_timeout(self, job_name, job_stage, job_artifacts, job_id):
        """Check End Timeout"""
        init = datetime.now()
        while not any(
            artifact.get("file_type") == "trace" for artifact in job_artifacts
        ):
            if (
                datetime.now() - init
            ).total_seconds() >= GITLAB_JOBS_LOGS_DOWNLOADER_END_JOB_TIMEOUT_SECONDS:
                logging.error(
                    'JOB="%s" STAGE="%s" PROJECT="%s" END JOB TIMEOUT WAS REACHED !"',
                    job_name,
                    job_stage,
                    self.project_name,
                )
                return True
            logging.warning(
                'NO LOGS FOR JOB="%s" STAGE="%s" PROJECT="%s"',
                job_name,
                job_stage,
                self.project_name,
            )
            time.sleep(GITLAB_JOBS_LOGS_DOWNLOADER_JOB_CHECK_INTERVAL_SECONDS)
            job_artifacts = self.get_job(job_id)["artifacts"]
        return False

    def download_logs(self, job_name, job_stage, job_id):
        """Download Job Logs"""
        filename = (
            f"{slugify(self.project_name)}"
            f"{GITLAB_JOBS_LOGS_DOWNLOADER_FILENAME_DELIMITER}"
            f"{slugify(job_stage)}"
            f"{GITLAB_JOBS_LOGS_DOWNLOADER_FILENAME_DELIMITER}"
            f"{slugify(job_name)}.log"
        )
        logs = self.session.get(
            f"{CI_API_V4_URL}/projects/{CI_PROJECT_ID}/jobs/{job_id}/trace",
            allow_redirects=True,
        )
        logging.info(
            'DOWNLOADING LOGS FOR JOB="%s" STAGE="%s" PROJECT="%s"',
            job_name,
            job_stage,
            self.project_name,
        )
        if logs.status_code != 200:
            logging.error(
                'UNABLE TO DOWNLOAD LOGS FOR JOB="%s" STAGE="%s" PROJECT="%s"',
                job_name,
                job_stage,
                self.project_name,
            )
            return
        try:
            with open(f"{GITLAB_JOBS_LOGS_DOWNLOADER_DIRECTORY}/{filename}", "wb") as f:
                f.write(logs.content)
            logging.info(
                "DESTINATION=%s/%s", GITLAB_JOBS_LOGS_DOWNLOADER_DIRECTORY, filename
            )
        except FileNotFoundError:
            logging.critical(
                "NO SUCH DIRECTORY GITLAB_JOBS_LOGS_DOWNLOADER_DIRECTORY=%s",
                GITLAB_JOBS_LOGS_DOWNLOADER_DIRECTORY,
            )
            os._exit(1)
        except PermissionError:
            logging.critical(
                "PERMISSION DENIED ON GITLAB_JOBS_LOGS_DOWNLOADER_DIRECTORY=%s",
                GITLAB_JOBS_LOGS_DOWNLOADER_DIRECTORY,
            )
            os._exit(1)

    def download_pipeline_jobs_logs(self):
        """Download Gitlab Pipeline Jobs Logs"""
        for pipeline_job in self.pipeline_jobs:
            job_id = pipeline_job["id"]
            job = self.get_job(job_id)
            job_artifacts = job["artifacts"]
            job_stage = job["stage"]
            job_name = job["name"]
            job_status = job["status"]

            if job_status in ["pending", "manual", "scheduled", "skipped", "created"]:
                logging.info(
                    'JOB="%s" STAGE="%s" PROJECT="%s" STATUS="%s" SKIP !',
                    job_name,
                    job_stage,
                    self.project_name,
                    job_status,
                )
                continue

            if self.check_running_timeout(job_name, job_stage, job_id, job_status):
                continue

            if self.check_end_timeout(job_name, job_stage, job_artifacts, job_id):
                continue

            self.download_logs(job_name, job_stage, job_id)


def main():
    """Main Function"""
    logging.info("Starting Gitlab Jobs Logs Downloader")
    for env_var in MANDATORY_ENV_VARS[:-1]:
        logging.info("%s=%s", env_var, os.environ.get(env_var))
    logging.info(
        "GITLAB_JOBS_LOGS_DOWNLOADER_DIRECTORY=%s",
        GITLAB_JOBS_LOGS_DOWNLOADER_DIRECTORY,
    )
    GitlabJobsLogsDownloader()


if __name__ == "__main__":
    main()
