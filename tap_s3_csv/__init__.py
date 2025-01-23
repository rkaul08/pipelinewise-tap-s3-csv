"""
Tap S3 csv main script
"""

from __future__ import annotations

import sys
from typing import Dict

import singer
import ujson
from singer import get_logger, metadata

from tap_s3_csv import s3
from tap_s3_csv.config import CONFIG_CONTRACT
from tap_s3_csv.discover import discover_streams
from tap_s3_csv.sync import sync_stream

LOGGER = get_logger("tap_s3_csv")

REQUIRED_CONFIG_KEYS = ["start_date", "bucket"]


def do_discover(config: Dict) -> None:
    """
    Discovers the source by connecting to the it and collecting information
    about the given tables/streams, it dumps the information to stdout
    :param config: connection and streams information
    :return: nothing
    """
    LOGGER.info("Starting discover")
    streams = discover_streams(config)
    if not streams:
        if not config.get("warning_if_no_files", False):
            raise Exception("No streams found")
    else:
        catalog = {"streams": streams}

        try:
            with open('catalog.json', 'w', encoding='utf-8') as f:
                ujson.dump(catalog, f, indent=2)
            LOGGER.info("Successfully wrote catalog to catalog.json")
        except Exception as e:
            LOGGER.error(f"Failed to write catalog file: {str(e)}")
            raise
        LOGGER.info("Finished discover")


def stream_is_selected(meta_data: Dict) -> bool:
    """
    Detects whether the stream is selected to be synced
    :param meta_data: stream metadata
    :return: True if selected, False otherwise
    """
    return meta_data.get((), {}).get("selected", True)


def do_sync(config: Dict, catalog: Dict, state: Dict) -> None:
    """
    Syncs every selected stream in the catalog and updates the state
    :param config: connection and streams information
    :param catalog: Streams catalog
    :param state: current state
    :return: Nothing
    """
    LOGGER.info("Starting sync.")

    for stream in catalog["streams"]:
        stream_name = stream["tap_stream_id"]
        mdata = metadata.to_map(stream["metadata"])
        try:
            table_spec = next(
                s
                for s in config["tables"]
                if s["table_name"] + config.get("table_suffix", "")
                == stream_name
            )
        except StopIteration as err:
            if not config.get("warning_if_no_files", False):
                raise Exception(
                    f"Expected table {stream_name} not found in catalog"
                ) from err
        if not stream_is_selected(mdata):
            LOGGER.info("%s: Skipping - not selected", stream_name)
            continue

        singer.write_state(state)
        key_properties = metadata.get(mdata, (), "table-key-properties")
        singer.write_schema(stream_name, stream["schema"], key_properties)

        LOGGER.info("%s: Starting sync", stream_name)
        counter_value = sync_stream(config, state, table_spec, stream)
        LOGGER.info("%s: Completed sync (%s rows)", stream_name, counter_value)

    LOGGER.info("Done syncing.")


def do_sync_run(config: Dict, catalog: Dict, state: Dict) -> None:
    """
    Syncs every selected stream in the catalog and updates the state designed for meltano run functionality
    :param config: connection and streams information
    :param catalog: Streams catalog
    :param state: current state
    :return: Nothing
    """
    LOGGER.info("Starting sync.")
    if catalog is None:
        do_discover(config: Dict)
        try:
            with open('catalog.json', 'r', encoding='utf-8') as f:
                catalog = ujson.load(f)
            LOGGER.info("Successfully loaded catalog from catalog.json")
        except Exception as e:
            LOGGER.error(f"Failed to load catalog file: {str(e)}")
            raise
            
    if state is None:
        state = {}

    for stream in catalog["streams"]:
        stream_name = stream["tap_stream_id"]
        mdata = metadata.to_map(stream["metadata"])
        try:
            table_spec = next(
                s
                for s in config["tables"]
                if s["table_name"] + config.get("table_suffix", "")
                == stream_name
            )
        except StopIteration as err:
            if not config.get("warning_if_no_files", False):
                raise Exception(
                    f"Expected table {stream_name} not found in catalog"
                ) from err
        if not stream_is_selected(mdata):
            LOGGER.info("%s: Skipping - not selected", stream_name)
            continue

        singer.write_state(state)
        key_properties = metadata.get(mdata, (), "table-key-properties")
        singer.write_schema(stream_name, stream["schema"], key_properties)

        LOGGER.info("%s: Starting sync", stream_name)
        counter_value = sync_stream(config, state, table_spec, stream)
        LOGGER.info("%s: Completed sync (%s rows)", stream_name, counter_value)

    LOGGER.info("Done syncing.")

@singer.utils.handle_top_exception(LOGGER)
def main() -> None:
    """
    Main function
    :return: None
    """
    args = singer.utils.parse_args(REQUIRED_CONFIG_KEYS)
    config = args.config

    # Reassign the config tables to the validated object
    config["tables"] = CONFIG_CONTRACT(config.get("tables", {}))

    try:
        for _ in s3.list_files_in_bucket(
            config["bucket"], s3_proxies=config.get("s3_proxies")
        ):
            break
        LOGGER.warning(
            "I have direct access to the bucket without assuming the configured role."
        )
    except Exception:
        s3.setup_aws_client(config)

    if args.discover:
        do_discover(args.config)
    elif args.properties:
        do_sync(config, args.properties, args.state)
    else:
        do_sync_run(config, args.properties, args.state)


if __name__ == "__main__":
    main()
