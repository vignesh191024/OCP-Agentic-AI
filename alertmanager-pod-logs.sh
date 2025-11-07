#!/bin/sh
# This script fetches logs for the pod with the given label
APP_LABEL=$1

# Get the latest pod name for the app
POD_NAME=$(oc get pods -n vigneshbaskar-dev -l app=${APP_LABEL} -o jsonpath='{.items[0].metadata.name}')

# Fetch logs and write to sidecar-mounted directory
oc logs $POD_NAME -n vigneshbaskar-dev > /var/log/app-logs/${POD_NAME}.log
