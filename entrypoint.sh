#!/bin/sh
# shellcheck source=/dev/null
. "${VIRTUAL_ENV}"/bin/activate
python3 "${VIRTUAL_ENV}/${SCRIPT}"
