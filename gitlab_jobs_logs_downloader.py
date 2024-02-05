#!/usr/bin/env python3
# coding: utf-8
# pyright: reportMissingImports=false, reportGeneralTypeIssues=false
# pyright: reportMissingModuleSource=false

"""Gitlab Jobs Logs Downloader"""

import logging
import os
import sys
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
        logging.info("RETRIEVING %s JOBS", len(self.pipeline_jobs.json()))
        self.download_pipeline_jobs_logs()

    def get_project(self):
        """Retrieve Gitlab Project"""
        project = self.session.get(f"{CI_API_V4_URL}/projects/{CI_PROJECT_ID}")
        if project.status_code != 200:
            logging.error("UNKNOWN GITLAB PROJECT ID %s !", CI_PROJECT_ID)
            os._exit(1)
        return project

    def get_pipeline_jobs(self):
        """Retrieve Gitlab Pipeline Jobs"""
        pipeline_jobs = self.session.get(
            f"{CI_API_V4_URL}/projects/{CI_PROJECT_ID}/pipelines/{CI_PIPELINE_ID}/jobs"
        )
        if pipeline_jobs.status_code != 200:
            logging.error(
                "UNKNOWN GITLAB PIPELINE ID %s FOR %s",
                CI_PIPELINE_ID,
                self.project_name,
            )
            os._exit(1)
        return pipeline_jobs

    def download_pipeline_jobs_logs(self):
        """Download Gitlab Pipeline Jobs Logs"""
        for job in self.pipeline_jobs.json():
            job_id = job["id"]
            job_stage = job["stage"]
            job_name = job["name"]
            job_artifacts = job["artifacts"]
            if not any(
                artifact.get("file_type") == "trace" for artifact in job_artifacts
            ):
                logging.warning(
                    'NO LOGS FOR JOB="%s" STAGE="%s" PROJECT="%s"',
                    job_name,
                    job_stage,
                    self.project_name,
                )
                continue
            logging.info(
                'DOWNLOADING LOGS FOR JOB="%s" STAGE="%s" PROJECT="%s"',
                job_name,
                job_stage,
                self.project_name,
            )
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
            if logs.status_code != 200:
                logging.info(
                    "UNABLE TO DOWNLOAD LOGS FOR JOB=%s STAGE=%s PROJECT=%s",
                    job_name,
                    job_stage,
                    self.project_name,
                )
                continue
            try:
                with open(
                    f"{GITLAB_JOBS_LOGS_DOWNLOADER_DIRECTORY}/{filename}", "wb"
                ) as f:
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
