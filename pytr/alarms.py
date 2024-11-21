import asyncio
from decimal import Decimal

from pytr.utils import get_logger, preview


class Alarms:
    def __init__(self, tr, isin=None, tgt_alarms=[]):
        self.tr = tr
        self.log = get_logger(__name__)
        self.isin = isin
        self.tgt_alarms = tgt_alarms

    async def alarms_loop(self):
        recv = 0
        await self.tr.price_alarm_overview()
        while True:
            _, subscription, response = await self.tr.recv()

            if subscription["type"] == "priceAlarms":
                recv += 1
                self.alarms = response
            else:
                print(f"unmatched subscription of type '{subscription['type']}':\n{preview(response)}")

            if recv == 1:
                return

    async def set_alarms(self):
        current_alarms = {}
        for a in self.alarms:
            if a["instrumentId"] == self.isin:
                current_alarms[Decimal(a["targetPrice"])] = a["id"]

        print(f"Current alarms for {self.isin}: {sorted(current_alarms.keys())}")

        new_alarms = []
        for a in self.tgt_alarms:
            ad = Decimal(a)
            if ad in current_alarms:
                print(f"Alarm {ad} already exists")
                del current_alarms[ad]
            else:
                print(f"Need to add alarm {ad}")
                new_alarms.append(ad)

        print(f"Alarms to add for {self.isin}: {new_alarms}")
        print(f"Alarms to remove for {self.isin}: {sorted(current_alarms.keys())}")

        action_count = 0
        for a in new_alarms:
            await self.tr.create_price_alarm(self.isin, float(a))
            action_count += 1

        for a in current_alarms:
            await self.tr.cancel_price_alarm(current_alarms.get(a))
            action_count += 1

        while action_count > 0:
            _, subscription, response = await self.tr.recv()
            # print(f"Subscription type: {subscription['type']}")
            # if subscription['type'] != "priceAlarms":
            #    print(f"Response: {response}")
            action_count -= 1
            # print(f"Action count left: {action_count}")
        return

    def overview(self):
        print("ISIN         status target")

        sorted_alarms = sorted(self.alarms, key=lambda x: (x["instrumentId"], x["targetPrice"]))
        for a in sorted_alarms:
            # sorted(positions, key=lambda x: x['netValue'], reverse=True):
            self.log.debug(f"  Processing {a} alarm")
            if self.isin is not None and a["instrumentId"] != self.isin:
                continue
            target_price = float(a["targetPrice"])

            print(f"{a['instrumentId']} {a['status']} {target_price:>7.2f}")

    def get(self):
        asyncio.get_event_loop().run_until_complete(self.alarms_loop())

        self.overview()

    def set(self):
        # get current alarms
        asyncio.get_event_loop().run_until_complete(self.alarms_loop())
        # set/remove alarms
        asyncio.get_event_loop().run_until_complete(self.set_alarms())
