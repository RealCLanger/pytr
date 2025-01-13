import asyncio

# import json
import locale

from pytr.utils import preview


class Watchlist:
    def __init__(self, tr):
        self.tr = tr

    async def watchlist_loop(self):
        recv = 0
        await self.tr.watchlist()
        recv += 1

        while recv > 0:
            subscription_id, subscription, response = await self.tr.recv()

            if subscription["type"] == "watchlist":
                recv -= 1
                self.watchlist = response
            else:
                print(f"unmatched subscription of type '{subscription['type']}':\n{preview(response)}")

            await self.tr.unsubscribe(subscription_id)

        # Convert dictionary to JSON string
        # json_data = json.dumps(self.watchlist, indent=4)

        # Print JSON string
        # print(json.dumps(self.watchlist, indent=4))

        # Populate name for each ISIN
        subscriptions = {}
        for pos in self.watchlist:
            isin = pos["instrumentId"]
            subscription_id = await self.tr.instrument_details(isin)
            subscriptions[subscription_id] = pos

        while len(subscriptions) > 0:
            subscription_id, subscription, response = await self.tr.recv()

            if subscription["type"] == "instrument":
                await self.tr.unsubscribe(subscription_id)
                pos = subscriptions.pop(subscription_id, None)
                pos["name"] = response["shortName"]
                pos["exchangeIds"] = response["exchangeIds"]
            else:
                print(f"unmatched subscription of type '{subscription['type']}':\n{preview(response)}")

        # Populate netValue for each ISIN
        subscriptions = {}
        for pos in self.watchlist:
            isin = pos["instrumentId"]
            if len(pos["exchangeIds"]) > 0:
                subscription_id = await self.tr.ticker(isin, exchange=pos["exchangeIds"][0])
                subscriptions[subscription_id] = pos

        while len(subscriptions) > 0:
            subscription_id, subscription, response = await self.tr.recv()

            if subscription["type"] == "ticker":
                await self.tr.unsubscribe(subscription_id)
                pos = subscriptions.pop(subscription_id, None)
                pos["price"] = float(response["last"]["price"])
            else:
                print(f"unmatched subscription of type '{subscription['type']}':\n{preview(response)}")

        # Print JSON string
        # print(json.dumps(self.watchlist, indent=4))

    def portfolio_to_csv(self, output_path):
        locale.setlocale(locale.LC_ALL, "de_DE")
        locale.setlocale(locale.LC_COLLATE, "de_DE.UTF-8")
        csv_lines = []
        for pos in sorted(self.watchlist, key=lambda x: locale.strxfrm(x["name"].lower()), reverse=False):
            csv_lines.append(
                f"{pos['name']};{pos['instrumentId']};{locale.format_string('%.4f', pos['price'], grouping=True)}"
            )

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("Name;ISIN;price\n")
            f.write("\n".join(csv_lines))

        print(f"Wrote {len(csv_lines) + 1} lines to {output_path}")

    def get(self):
        asyncio.get_event_loop().run_until_complete(self.watchlist_loop())
