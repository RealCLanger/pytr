import asyncio
import csv
import platform
import sys

from pytr.utils import get_logger, preview


class SavingsPlans:
    def __init__(self, tr, fp=None):
        self.tr = tr
        self.fp = fp
        self.log = get_logger(__name__)
        self.savings_plans = []

    async def savings_plans_loop(self):
        await self.tr.savings_plan_overview()
        while True:
            _, subscription, response = await self.tr.recv()

            if subscription["type"] == "savingsPlans":
                self.savings_plans = response.get("savingsPlans", [])
                return
            else:
                print(f"unmatched subscription of type '{subscription['type']}':\n{preview(response)}")

    def overview(self):
        if not self.savings_plans:
            print("No savings plans found.")
            return

        fieldnames = [
            "instrumentId",
            "amount",
            "interval",
            "nextExecutionDate",
            "previousExecutionDate",
            "paused",
        ]

        if self.fp == sys.stdout:
            header = "  ".join(f"{f}" for f in fieldnames)
            print(header)
            for plan in self.savings_plans:
                row = "  ".join(str(plan.get(f, "")) for f in fieldnames)
                print(row)
        else:
            print(f"Writing savings plans to file {self.fp.name}...")
            lineterminator = "\n" if platform.system() == "Windows" else "\r\n"
            writer = csv.DictWriter(
                self.fp,
                fieldnames=fieldnames,
                delimiter=";",
                lineterminator=lineterminator,
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(self.savings_plans)
            self.fp.close()

    def get(self):
        async def get_and_close():
            await self.savings_plans_loop()
            await self.tr.close()

        asyncio.run(get_and_close())
        self.overview()
