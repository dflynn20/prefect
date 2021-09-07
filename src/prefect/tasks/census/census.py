import time

import re
import requests

from prefect import Task
from prefect.utilities.tasks import defaults_from_attrs


MIN_WAIT_TIME, DEFAULT_WAIT_TIME = 5, 60


class CensusSyncTask(Task):
    """
    Task for running Census connector sync jobs.

    This task assumes the user has a Census sync already configured and is attempting to orchestrate the
    sync using Prefect task to send a post to the API within a prefect flow. Copy and paste from the api
    trigger section on the configuration page in the `api_trigger` param to set a default sync.

    Args:
        - api_trigger (str, optional): default sync to trigger, if none is specified in `run`
        - **kwargs (dict, optional): additional kwargs to pass to the base Task constructor
    """

    def __init__(self, api_trigger=None, **kwargs):
        self.api_trigger = api_trigger
        super().__init__(**kwargs)

    @defaults_from_attrs("api_trigger")
    def run(
        self, api_trigger: str, poll_status_every_n_seconds: int = DEFAULT_WAIT_TIME
    ) -> dict:
        """
        Task run method for Census syncs.

        An invocation of `run` will attempt to start a sync job for the specified `api_trigger`. `run`
        will poll Census for the sync status, and will only complete when the sync has completed or
        when it receives an error status code from the trigger API call.

        Format of api_trigger:
            - "https://bearer:secret-token:s3cr3t@app.getcensus.com/api/v1/syncs/123/trigger"

        Args:
            - api_trigger (str): if not specified in run, it will pull from the default for the
                CensusSyncTask constructor. Keyword argument.
            - poll_status_every_n_seconds (int, optional): this task polls the Census API for the sync's
                status. If provided, this value will override the default polling time of
                60 seconds and it has a minimum wait time of 5 seconds. Keyword argument.

        Returns:
            - dict: dictionary of statistics returned by Census on the specified sync
        """

        if not api_trigger:
            raise ValueError(
                """Value for parameter `api_trigger` must be provided. See Census sync
                                configuration page."""
            )

        pattern = r"https:\/\/bearer:secret-token:(.*)@app.getcensus.com\/api\/v1\/syncs\/(\d*)\/trigger"
        url_pattern = re.compile(pattern)

        # Making sure it is a valid api trigger.
        confirmed_pattern = url_pattern.match(api_trigger)

        if not confirmed_pattern:
            raise ValueError(
                """Invalid parameter for `api_trigger` please paste directly from the Census
                                sync configuration page. This is CaSe SenSITiVe."""
            )

        secret, sync_id = confirmed_pattern.groups()
        response = requests.post(api_trigger)

        if response.status_code != 200:
            error_string = f"Sent POST, failed with status code {response.status_code}: {response.text}."
            raise ValueError(error_string)

        sleep_time = max(MIN_WAIT_TIME, poll_status_every_n_seconds)

        self.logger.info(
            f"Started Census sync {sync_id}, sleep time set to {sleep_time} seconds."
        )

        sync_run_id = response.json()["data"]["sync_run_id"]
        sr_url = f"https://bearer:secret-token:{secret}@app.getcensus.com/api/v1/sync_runs/{sync_run_id}"
        log_url = f"https://app.getcensus.com/syncs/{sync_id}/sync-history"

        result = {}

        start_time = time.time()
        while True:
            time.sleep(sleep_time)
            status_response = requests.get(sr_url)
            response_dict = status_response.json()
            if status_response.status_code != 200 or "data" not in response_dict.keys():
                raise ValueError(
                    f"Getting status of sync failed, please visit Census Logs at {log_url} to see more."
                )
            result = response_dict["data"]
            status = result["status"]
            if status == "working":
                self.logger.info(
                    f"Sync {sync_id} still running after {round(time.time()-start_time, 2)} seconds."
                )
                continue
            break

        self.logger.info(
            f"Sync {sync_id} has finished running after {round(time.time()-start_time, 2)} seconds."
        )
        self.logger.info(f"View details here: {log_url}.")

        # Returns a dictionary of:
        # {
        #   'error_message': None / String,
        #   'records_failed': Int / None,
        #   'records_invalid': Int / None,
        #   'records_processed': Int / None,
        #   'records_updated': Int / None,
        #   'status': 'completed'/'working'/'failed'
        # }

        return result
