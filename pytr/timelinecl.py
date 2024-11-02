import json
from datetime import datetime

from .event import Event
from .transactions import export_transactions
from .utils import get_logger


def is_likely_same_but_newer(event, old_event):
    if event["title"] != old_event["title"]:
        return False

    if (
        event["subtitle"] != "Limit-Sell-Order"
        and event["subtitle"] != "Limit-Buy-Order"
        and event["subtitle"] != "Sparplan ausgeführt"
    ):
        return False

    if event["subtitle"] != old_event["subtitle"]:
        return False

    # Check timestamps
    fmt = "%Y-%m-%dT%H:%M:%S.%f%z"
    date_new = datetime.strptime(event["timestamp"], fmt)
    date_old = datetime.strptime(old_event["timestamp"], fmt)

    if date_new < date_old:
        return False

    return abs((date_new - date_old).total_seconds() * 1000) <= 500


class UnsupportedEventError(Exception):
    pass


class Timeline:
    def __init__(self, tr, max_age_timestamp):
        self.tr = tr
        self.log = get_logger(__name__)
        self.received_detail = 0
        self.requested_detail = 0
        self.skipped_detail = 0
        self.events_without_docs = []
        self.events_with_docs = []
        self.num_timelines = 0
        self.timeline_events = {}
        self.max_age_timestamp = max_age_timestamp

    async def get_next_timeline_transactions(self, response, dl):
        """
        Get timelines transactions and save time in list timelines.
        Extract timeline transactions events and save them in list timeline_events

        """
        if response is None:
            # empty response / first timeline
            self.log.info("Subscribing to #1 timeline transactions")
            self.num_timelines = 0
            await self.tr.timeline_transactions()
        else:
            self.num_timelines += 1
            added_last_event = True
            for event in response["items"]:
                if (
                    self.max_age_timestamp == 0
                    or datetime.fromisoformat(event["timestamp"][:19]).timestamp() >= self.max_age_timestamp
                ):
                    event["source"] = "timelineTransaction"
                    self.timeline_events[event["id"]] = event
                else:
                    added_last_event = False
                    break

            self.log.info(f"Received #{self.num_timelines:<2} timeline transactions")
            after = response["cursors"].get("after")
            if (after is not None) and added_last_event:
                self.log.info(f"Subscribing #{self.num_timelines + 1:<2} timeline transactions")
                await self.tr.timeline_transactions(after)
            else:
                # last timeline is reached
                self.log.info("Received last relevant timeline transaction")
                await self.get_next_timeline_activity_log(None, dl)

    async def get_next_timeline_activity_log(self, response, dl):
        """
        Get timelines acvtivity log and save time in list timelines.
        Extract timeline acvtivity log events and save them in list timeline_events

        """
        if response is None:
            # empty response / first timeline
            self.log.info("Awaiting #1  timeline activity log")
            self.num_timelines = 0
            await self.tr.timeline_activity_log()
        else:
            self.num_timelines += 1
            added_last_event = False
            for event in response["items"]:
                if (
                    self.max_age_timestamp == 0
                    or datetime.fromisoformat(event["timestamp"][:19]).timestamp() >= self.max_age_timestamp
                ):
                    if event["id"] in self.timeline_events:
                        self.log.warning(f"Received duplicate event {event['id']}")
                    else:
                        added_last_event = True
                    event["source"] = "timelineActivity"
                    self.timeline_events[event["id"]] = event
                else:
                    break

            self.log.info(f"Received #{self.num_timelines:<2} timeline activity log")
            after = response["cursors"].get("after")
            if (after is not None) and added_last_event:
                self.log.info(f"Subscribing #{self.num_timelines + 1:<2} timeline activity log")
                await self.tr.timeline_activity_log(after)
            else:
                self.log.info("Received last relevant timeline activity log")
                await self._get_timeline_details(dl)

    async def _get_timeline_details(self, dl):
        """
        request timeline details
        """
        for event in self.timeline_events.values():
            action = event.get("action")
            msg = ""
            if action is None:
                if event.get("actionLabel") is None:
                    msg += "Skip: no action"
            elif action.get("type") != "timelineDetail":
                msg += f"Skip: action type unmatched ({action['type']})"
            elif action.get("payload") != event["id"]:
                msg += f"Skip: payload unmatched ({action['payload']})"

            if msg != "":
                self.events_without_docs.append(event)
                self.log.debug(f"{msg} {event['title']}: {event.get('body')} ")
            else:
                self.requested_detail += 1
                await self.tr.timeline_detail_v2(event["id"])
        self.log.info("All timeline details requested")
        self.check_if_done(dl)

    def process_timelineDetail(self, response, dl):
        """
        process timeline details response
        download any associated docs
        create other_events.json, events_with_documents.json and account_transactions.csv
        """

        event = self.timeline_events.get(response["id"], None)
        if event is None:
            raise UnsupportedEventError(response["id"])

        self.received_detail += 1
        event["details"] = response

        max_details_digits = len(str(self.requested_detail))
        self.log.info(
            f"{self.received_detail:>{max_details_digits}}/{self.requested_detail}: "
            + f"{event['title']} -- {event['subtitle']} - {event['timestamp'][:19]}"
        )
        self.events_without_docs.append(event)

        self.check_if_done(dl)

    def check_if_done(self, dl):
        if (self.received_detail + self.skipped_detail) == self.requested_detail:
            self.finish_timeline_details(dl)

    def finish_timeline_details(self, dl):
        self.log.info("Received all details")
        if self.skipped_detail > 0:
            self.log.warning(f"Skipped {self.skipped_detail} unsupported events")

        dl.output_path.mkdir(parents=True, exist_ok=True)

        # drop all entries that are no effective events
        filtered_events = []
        for event in self.events_without_docs:
            if Event.from_dict(event).event_type is not None:
                filtered_events.append(event)
        self.events_without_docs = filtered_events

        all_events_path = dl.output_path / "all_events.json"
        if all_events_path.exists():
            with open(all_events_path, "r", encoding="utf-8") as f:
                old_events = json.load(f)

                cur_events = {}
                # drop duplicates in old events
                for event in old_events:
                    idtodel = None
                    for id in cur_events:
                        cur_event = cur_events[id]
                        if is_likely_same_but_newer(event, cur_event):
                            print(
                                f"Attention: Dropping potential duplicate event {id} from {cur_event['timestamp']} due to newer event {event['id']} from {event['timestamp']}."
                            )
                            idtodel = id
                            break
                    if idtodel is not None:
                        cur_events.pop(id)
                    cur_events[event["id"]] = event

                for event in self.events_without_docs:
                    idtodel = None
                    for id in cur_events:
                        cur_event = cur_events[id]
                        if event["id"] != id and is_likely_same_but_newer(event, cur_event):
                            print(
                                f"Attention: Dropping existing event {id} from {cur_event['timestamp']} due to newer event {event['id']} from {event['timestamp']}."
                            )
                            idtodel = id
                            break
                    if idtodel is not None:
                        cur_events.pop(id)
                    cur_events[event["id"]] = event

                self.events_without_docs = sorted(cur_events.values(), key=lambda value: value["timestamp"])

        with open(all_events_path, "w", encoding="utf-8") as f:
            json.dump(self.events_without_docs, f, ensure_ascii=False, indent=2)

        export_transactions(
            dl.output_path / "all_events.json",
            dl.output_path / "account_transactions.csv",
            sort=dl.sort_export,
        )

        dl.dl_done = True
