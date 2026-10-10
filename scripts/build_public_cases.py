#!/usr/bin/env python3
"""
Build data/public_cases.json: shipments reconstructed from public enforcement cases.

    python scripts/build_public_cases.py
    python scripts/run_massive_benchmark.py --arm rules --cases data/public_cases.json \
        --sanctions-index %TEMP%/floorline-sanctions/index.json \
        --out data/benchmark_results/public_rules_all.json

Why this exists
---------------
Every other number in this repository is measured on a synthetic corpus the project
wrote itself, and a corpus written by the system's authors tests the system against
its authors' idea of fraud. These cases come from the other direction: each is a
shipment as the paperwork presented it in a case a regulator or prosecutor later
made public -- a BIS Temporary Denial Order, an OFAC settlement, a Commerce
circumvention finding, an EPPO or OLAF release -- with the URL and a verbatim quote.
Nothing in a shipment below is shaped to trigger a rule. Where the source states a
fact (the parties, the route, the declared value, the HS code or the goods), it is
used as stated; where it does not, the field takes a neutral default that is the
same for the case and its honest counterpart.

Read the results with three limits in mind:

  * Retrospective lists. Parties are screened against today's OFAC and UN lists,
    and several were designated BECAUSE of the case. A hit says the list would
    catch the party now, not that it would have at the time.
  * What a booking can show. Origin fraud is decided by where the inputs came from,
    which no booking record carries. A shipment of Vietnamese-declared plywood made
    from Chinese veneer looks exactly like one made from Vietnamese veneer, so those
    pairs are expected to be indistinguishable here, and the report says so rather
    than tuning a rule until they are not.
  * Small n. Nineteen pairs. A single case moves recall by five points.

Neutral defaults, identical within every pair: 50 prior shipments for the shipper
(neither new nor whitelisted), freight equal to the lane baseline verifier.py
already uses (ratio 1.0, so FREIGHT_ANOMALY cannot fire on an assumption), FCA
incoterm. Where the source gives an aggregate value and a shipment count, the
declared value is the average; where it gives neither, the value is marked
assumed in `assumptions`.

Dropped, with the reason:
  Cadence (BIS 2025)       EDA software and licences, not a shipment
  SkyGeek (OFAC 2024)      the two UAE consignees are unnamed, so the one check
                           that matters cannot be run
  Pegasus (OFAC 2026)      the designated supplier is unnamed
  Shoes, France (EPPO)     no declared value is stated, only the duty avoided
  Bicycles, NL (EPPO)      no per-shipment value or declared origin is stated
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "data" / "public_cases.json"

NEUTRAL_TX_COUNT = 50


def _src(authority: str, date: str, url: str, quote: str, *more: str) -> dict:
    return {"authority": authority, "date": date, "urls": [url, *more], "quote": quote}


# (case_ref, typology, title, source, attack shipment, counterpart shipment,
#  assumptions, what a booking can show)
#
# Shipments list only the fields that differ from _defaults(). The counterpart is
# the legitimate trade the fraud imitated: same goods, with the facts the source
# says were false replaced by true ones.
PAIRS: list[dict] = [
    # ---- dual-use and export-control transshipment ------------------------
    {
        "ref": "BIS-TDO-2023-GOLTSEV",
        "typology": "dual_use_transshipment",
        "title": "US microcontrollers and SRAM routed to Russian defence buyers via a UAE free-zone company",
        "source": _src(
            "BIS Temporary Denial Order", "2023-11-14",
            "https://www.govinfo.gov/content/pkg/FR-2023-11-14/html/2023-25005.htm",
            "Using SH Brothers and SN Electronics, Nasriddinov and Goltsev shipped the items "
            "through various intermediaries located in third countries, including China, "
            "India, Turkey, and the United Arab Emirates.",
        ),
        "attack": {
            "origin": "New York, United States", "shipper_country": "United States",
            "shipper_company": "SH Brothers Group, Inc.",
            "destination": "Ajman, United Arab Emirates", "receiver_country": "United Arab Emirates",
            "receiver_company": "Suntronic FZE",
            "hs_code": "8542.31", "transport_mode": "air",
            "cargo_description": "Microcontrollers (ATMEGA8A-MN) and SRAM integrated circuits",
            # 27 shipments worth about $1,086,058 to Suntronic, per the order.
            "declared_value": 40_224, "weight_kg": 25,
        },
        "counterpart": {
            "shipper_company": "Atlantic Components Distribution Inc.",
            "destination": "Munich, Germany", "receiver_country": "Germany",
            "receiver_company": "Isar Steuerungstechnik GmbH",
        },
        "assumptions": ["weight 25 kg for an air parcel of ICs"],
        "booking_shows": "The goods are controlled (HS 8542) and the consignee is a UAE free-zone trader. The Russian end users never appear on the paperwork.",
    },
    {
        "ref": "BIS-TDO-2022-LIVSHITS",
        "typology": "dual_use_transshipment",
        "title": "Oscilloscope worth about $25,000 declared as 'Used' at $2,482 to stay under the EEI threshold, via Hamburg to Russia",
        "source": _src(
            "BIS Temporary Denial Order", "2022-12-16",
            "https://www.govinfo.gov/content/pkg/FR-2022-12-16/html/2022-27347.htm",
            "The shipment was declared with DHL to be a ``Oscilloscope--Used, No Warr'' with "
            "the declared value of $2,482, an amount under the $2,500 threshold which would "
            "have required Respondents to file an EEI submission",
        ),
        "attack": {
            "origin": "New York, United States", "shipper_country": "United States",
            "shipper_company": "Advanced Web Services",
            "destination": "Hamburg, Germany", "receiver_country": "Germany",
            "receiver_company": "Freight consolidator, Hamburg (unnamed in the order)",
            "hs_code": "9030.20", "transport_mode": "air",
            "cargo_description": "Oscilloscope--Used, No Warr",
            "declared_value": 2_482, "weight_kg": 12,
        },
        "counterpart": {
            "shipper_company": "Hudson Test Equipment LLC",
            "receiver_company": "Hanse Messtechnik Labor GmbH",
            "cargo_description": "Mixed signal oscilloscope, new, with warranty",
            # The order: bought for about $25,000.
            "declared_value": 25_000,
        },
        "assumptions": ["HS 9030 mapped by us from the goods (the order gives ECCN 3A992.a)", "weight 12 kg"],
        "booking_shows": "Controlled goods, declared $18 under a reporting threshold, as 'Used' when the item is new.",
    },
    {
        "ref": "BIS-TDO-2023-PATSULYA",
        "typology": "dual_use_transshipment",
        "title": "Aircraft brake assemblies for a Russian airline consigned to a Maldives cargo agent, destination changed to Turkey after a forwarder raised concerns",
        "source": _src(
            "BIS Temporary Denial Order", "2023-05-19",
            "https://www.govinfo.gov/content/pkg/FR-2023-05-19/html/2023-10750.htm",
            "Although Besedin initially told the vendor that the brake assemblies were destined "
            "for Intermodal, the information was later changed to reflect shipping to Turkey "
            "after Besedin was alerted by a U.S. freight forwarder of issues with shipping to "
            "Intermodal.",
        ),
        "attack": {
            "origin": "Miami, United States", "shipper_country": "United States",
            "shipper_company": "MIC P&I, LLC",
            "destination": "Male, Maldives", "receiver_country": "Maldives",
            "receiver_company": "Intermodal Maldives",
            "hs_code": "8807.20", "transport_mode": "air",
            "cargo_description": "Aircraft wheel brake assembly, Goodrich P/N 2-1740-1",
            "declared_value": 105_000, "weight_kg": 120,
            "route_details": (
                "Miami, United States to Male, Maldives; destination amended after booking "
                "to Istanbul, Turkey"
            ),
        },
        "counterpart": {
            "shipper_company": "Gulfstream Aero Spares LLC",
            "destination": "Singapore, Singapore", "receiver_country": "Singapore",
            "receiver_company": "Changi Line Maintenance Pte Ltd",
            "route_details": "Miami, United States to Singapore; direct air freight",
        },
        "assumptions": ["origin city Miami (the order places MIC P&I in Florida)", "HS 8807.20 mapped by us (ECCN 9A991.d)", "weight 120 kg"],
        "booking_shows": "A cargo agent as consignee for airline parts, and a destination changed after booking.",
    },
    {
        "ref": "BIS-TDO-2024-SKYTECHNIC",
        "typology": "dual_use_transshipment",
        "title": "US aircraft starter generators bought for a Russian MRO through Hong Kong shell companies",
        "source": _src(
            "BIS Temporary Denial Order", "2024-06-17",
            "https://www.govinfo.gov/content/pkg/FR-2024-06-17/html/2024-13258.htm",
            "SkyTechnic began using the Skywind, Hong Fan, and Lufeng aliases in Hong Kong in "
            "an effort to conceal its Russian connections and transship U.S. aircraft parts "
            "through Hong Kong to Russia.",
        ),
        "attack": {
            "origin": "Miami, United States", "shipper_country": "United States",
            "shipper_company": "US aircraft parts supplier (unnamed in the order)",
            "destination": "Hong Kong, Hong Kong", "receiver_country": "Hong Kong",
            "receiver_company": "Lufeng Limited",
            "hs_code": "8511.40", "transport_mode": "air",
            "cargo_description": "Aircraft engine starter generators",
            # About 22 shipments worth $388,000 to Lufeng.
            "declared_value": 17_636, "weight_kg": 30,
        },
        "counterpart": {
            "receiver_company": "Tsing Yi Aero Components Ltd",
        },
        "assumptions": ["origin city Miami", "HS 8511.40 mapped by us (ECCN 9A991)", "weight 30 kg"],
        "booking_shows": "An ordinary-looking Hong Kong buyer of aircraft parts. The Russian link is in website hosting and email domains, not in the booking.",
    },
    {
        "ref": "BIS-TDO-2023-PETROV",
        "typology": "dual_use_transshipment",
        "title": "Microcontrollers sold to a Cyprus 'fabless manufacturer' that was a pass-through forwarder for a St. Petersburg buyer",
        "source": _src(
            "BIS Temporary Denial Order", "2023-09-07",
            "https://www.govinfo.gov/content/pkg/FR-2023-09-07/html/2023-19332.htm",
            "falsely claiming that Astrafteros is a ``fabless manufacturer (fire security "
            "systems sphere),'' when in fact Petrov operates Astrafteros as a pass-through "
            "freight-forwarder on behalf of Electrocom.",
        ),
        "attack": {
            "origin": "Dallas, United States", "shipper_country": "United States",
            "shipper_company": "US electronics distributor (unnamed in the order)",
            "destination": "Larnaca, Cyprus", "receiver_country": "Cyprus",
            "receiver_company": "Astrafteros Technokosmos LTD",
            "consignee_name": "Ultra Trade Service LLC",
            "hs_code": "8542.31", "transport_mode": "air",
            "cargo_description": "16-bit flash microcontrollers",
            "declared_value": 20_000, "weight_kg": 8,
        },
        "counterpart": {
            "receiver_company": "Kition Fire Detection Systems Ltd",
            "consignee_name": "Kition Fire Detection Systems Ltd",
        },
        "assumptions": ["origin city Dallas", "declared value $20,000 (the order states no values)", "weight 8 kg"],
        "booking_shows": "Controlled goods to a small Cyprus buyer, with an ultimate consignee in a third country (Latvia).",
    },
    {
        "ref": "BIS-2026-AMAT",
        "typology": "dual_use_transshipment",
        "title": "Ion implanters shipped to a Korean affiliate for assembly, then onward to an Entity-Listed Chinese customer",
        "source": _src(
            "BIS", "2026-02-12",
            "https://www.bis.gov/press-release/applied-materials-pay-252-million-penalty-bis-illegally-exporting-semiconductor-manufacturing-equipment",
            "by shipping ion implanters first to AMK in Korea for assembly, and then onward "
            "to China, without applying for and receiving an export license.",
        ),
        "attack": {
            "origin": "San Francisco, United States", "shipper_country": "United States",
            "shipper_company": "Applied Materials, Inc.",
            "destination": "Busan, South Korea", "receiver_country": "South Korea",
            "receiver_company": "Applied Materials Korea, Ltd.",
            "hs_code": "8486.20", "transport_mode": "sea",
            "cargo_description": "Ion implanter, semiconductor manufacturing equipment, for assembly",
            "declared_value": 4_000_000, "weight_kg": 18_000,
        },
        "counterpart": {},
        "assumptions": ["declared value $4,000,000 per implanter (the release states $126M in total)", "weight 18 t", "sea via Busan"],
        "booking_shows": "Nothing: the first leg is a legitimate shipment to an affiliate. The violation is the onward leg, which is a second booking.",
    },
    {
        "ref": "OLAF-2026-VEHICLES-RU",
        "typology": "dual_use_transshipment",
        "title": "Used vehicles declared for importers in Central Asia and the Caucasus, never imported there, traced to Russia",
        "source": _src(
            "EU OLAF", "2026-01-26",
            "https://anti-fraud.ec.europa.eu/media-corner/news/olaf-coordinates-international-investigation-suspected-circumvention-eu-sanctions-involving-over-760-2026-01-26_en",
            "Although the vehicles were declared as destined for Türkiye, evidence gathered by "
            "Polish customs suggested that their actual destination was Russia.",
        ),
        "attack": {
            "origin": "Gdansk, Poland", "shipper_country": "Poland",
            "shipper_company": "Used vehicle exporter, Poland (unnamed in the release)",
            "destination": "Almaty, Kazakhstan", "receiver_country": "Kazakhstan",
            "receiver_company": "Declared importer, Kazakhstan (unnamed in the release)",
            "hs_code": "8704.21", "transport_mode": "road",
            "cargo_description": "Used goods transport vehicle",
            "declared_value": 18_000, "weight_kg": 3_500,
        },
        "counterpart": {
            "receiver_company": "Almaty Fleet Leasing LLP",
        },
        "assumptions": ["HS 8704 mapped by us ('used transport vehicles')", "value $18,000 and weight 3.5 t per vehicle"],
        "booking_shows": "A used vehicle to a Kazakh importer. That the importer never imported it is only visible after the fact.",
    },

    # ---- sanctions and logistics ---------------------------------------
    {
        "ref": "OFAC-2022-TOLL",
        "typology": "sanctions_logistics",
        "title": "Australian freight forwarder handled shipments to, from or through DPRK, Iran and Syria",
        "source": _src(
            "OFAC", "2022-04-25",
            "https://ofac.treasury.gov/recent-actions/20220425",
            "These payments were in connection with sea, air, and rail shipments conducted by "
            "Toll, its affiliates, or suppliers to, from, or through the Democratic People's "
            "Republic of Korea, Iran, or Syria",
        ),
        "attack": {
            "origin": "Singapore, Singapore", "shipper_country": "Singapore",
            "shipper_company": "Freight customer (unnamed in the release)",
            "destination": "Bandar Abbas, Iran", "receiver_country": "Iran",
            "receiver_company": "Consignee, Iran (unnamed in the release)",
            "hs_code": "8481.80", "transport_mode": "sea",
            "cargo_description": "Industrial valves",
            "declared_value": 30_000, "weight_kg": 2_000,
        },
        "counterpart": {
            "destination": "Jebel Ali, United Arab Emirates", "receiver_country": "United Arab Emirates",
            "receiver_company": "Jebel Ali Process Supplies LLC",
        },
        "assumptions": ["goods, values and parties are not stated; industrial valves at $30,000 stand in for 'shipments'"],
        "booking_shows": "The destination country.",
    },
    {
        "ref": "OFAC-2024-CHROBINSON",
        "typology": "sanctions_logistics",
        "title": "Non-US subsidiaries of a US broker arranged freight for shipments involving Cuba and Iran",
        "source": _src(
            "OFAC", "2024-12-13",
            "https://ofac.treasury.gov/recent-actions/20241213",
            "82 apparent violations by five of its non-U.S. subsidiaries, which provided "
            "freight brokerage or transportation services for shipments in apparent violation "
            "of OFAC sanctions on Cuba and Iran.",
        ),
        "attack": {
            "origin": "Veracruz, Mexico", "shipper_country": "Mexico",
            "shipper_company": "Freight customer (unnamed in the release)",
            "destination": "Havana, Cuba", "receiver_country": "Cuba",
            "receiver_company": "Consignee, Cuba (unnamed in the release)",
            "hs_code": "3923.30", "transport_mode": "sea",
            "cargo_description": "Plastic bottles and containers",
            "declared_value": 22_000, "weight_kg": 6_000,
        },
        "counterpart": {
            "destination": "Kingston, Jamaica", "receiver_country": "Jamaica",
            "receiver_company": "Kingston Beverage Packaging Ltd",
        },
        "assumptions": ["goods, values and parties are not stated; plastic containers stand in"],
        "booking_shows": "The destination country.",
    },
    {
        "ref": "OFAC-2025-FRACHT",
        "typology": "sanctions_logistics",
        "title": "Houston forwarder booked a blocked Venezuelan state airline, flying an aircraft blocked as operated by Mahan Air, for a Mexico-Argentina shipment",
        "source": _src(
            "OFAC", "2025-09-03",
            "https://ofac.treasury.gov/recent-actions/20250903_33",
            "Fracht contracted with a blocked Government of Venezuela airline to transport goods "
            "to Argentina from Mexico on behalf of its customer.",
        ),
        "attack": {
            "origin": "Mexico City, Mexico", "shipper_country": "Mexico",
            "shipper_company": "Freight customer (unnamed in the release)",
            "destination": "Buenos Aires, Argentina", "receiver_country": "Argentina",
            "receiver_company": "Consignee, Argentina (unnamed in the release)",
            "hs_code": "8431.43", "transport_mode": "air",
            "cargo_description": "Drilling machinery parts",
            "declared_value": 60_000, "weight_kg": 900,
            "route_details": (
                "Mexico City, Mexico to Buenos Aires, Argentina; air charter on an aircraft "
                "operated by Mahan Air for a Government of Venezuela airline"
            ),
        },
        "counterpart": {
            "route_details": "Mexico City, Mexico to Buenos Aires, Argentina; scheduled air freight",
        },
        "assumptions": ["goods and values are not stated; drilling parts stand in", "the carrier is stated in route_details because no booking field carries it"],
        "booking_shows": "Only the carrier, which this system does not screen.",
    },

    # ---- origin fraud and transshipment --------------------------------
    {
        "ref": "ITA-2023-PLYWOOD-VN",
        "typology": "origin_transshipment",
        "title": "Plywood completed in Vietnam from Chinese veneers and cores, declared Vietnamese",
        "source": _src(
            "US Department of Commerce (ITA)", "2023-07-20",
            "https://www.govinfo.gov/content/pkg/FR-2023-07-20/html/2023-15431.htm",
            "we determine, pursuant to section 781(b) of the Act and 19 CFR 351.225(g), that "
            "imports of hardwood plywood completed in Vietnam are circumventing the Orders.",
        ),
        "attack": {
            "origin": "Hai Phong Port, Vietnam", "shipper_country": "Vietnam",
            "shipper_company": "Vietnamese plywood exporter (named generically)",
            "destination": "Long Beach, United States", "receiver_country": "United States",
            "receiver_company": "US plywood importer (named generically)",
            "hs_code": "4412.33", "transport_mode": "sea",
            "cargo_description": "Hardwood plywood, 18 mm, Vietnam origin",
            "declared_value": 28_000, "weight_kg": 22_000,
        },
        "counterpart": {},
        "assumptions": ["value and weight per container assumed", "exporter left unnamed: the finding is country-wide"],
        "booking_shows": "Nothing: the veneer's origin is not on a booking.",
    },
    {
        "ref": "ITA-2023-SOLAR-SEA",
        "typology": "origin_transshipment",
        "title": "Solar modules completed in Cambodia from Chinese wafers, declared Cambodian",
        "source": _src(
            "US Department of Commerce (ITA)", "2023-08-23",
            "https://www.govinfo.gov/content/pkg/FR-2023-08-23/html/2023-18161.htm",
            "that were produced in Cambodia, Malaysia, Thailand, or Vietnam, from wafers "
            "produced in China;",
        ),
        "attack": {
            "origin": "Sihanoukville, Cambodia", "shipper_country": "Cambodia",
            "shipper_company": "Cambodian solar module exporter (named generically)",
            "destination": "Los Angeles, United States", "receiver_country": "United States",
            "receiver_company": "US solar distributor (named generically)",
            "hs_code": "8541.43", "transport_mode": "sea",
            "cargo_description": "Crystalline silicon photovoltaic modules, Cambodia origin",
            "declared_value": 120_000, "weight_kg": 18_000,
        },
        "counterpart": {},
        "assumptions": ["value and weight per container assumed"],
        "booking_shows": "Nothing: the wafer's origin is not on a booking.",
    },
    {
        "ref": "ITA-2024-STAPLES-VN",
        "typology": "origin_transshipment",
        "title": "Collated staples formed in Vietnam from Chinese steel wire, declared Vietnamese",
        "source": _src(
            "US Department of Commerce (ITA)", "2024-01-30",
            "https://www.govinfo.gov/content/pkg/FR-2024-01-30/html/2024-01792.htm",
            "imports of collated staples completed in Vietnam using steel wire or wire bands "
            "manufactured in China, as opposed to only wire bands manufactured in China, have "
            "circumvented the Orders on a country-wide basis",
        ),
        "attack": {
            "origin": "Cat Lai Port, Ho Chi Minh City, Vietnam", "shipper_country": "Vietnam",
            "shipper_company": "Vietnamese staple manufacturer (named generically)",
            "destination": "Savannah, United States", "receiver_country": "United States",
            "receiver_company": "US fastener distributor (named generically)",
            "hs_code": "8305.20", "transport_mode": "sea",
            "cargo_description": "Collated steel staples, Vietnam origin",
            "declared_value": 36_000, "weight_kg": 20_000,
        },
        "counterpart": {},
        "assumptions": ["value and weight per container assumed"],
        "booking_shows": "Nothing: the wire's origin is not on a booking.",
    },
    {
        "ref": "ITA-2023-LWRPT-VN",
        "typology": "origin_transshipment",
        "title": "Light-walled rectangular pipe made in Vietnam from Chinese hot-rolled steel, declared Vietnamese",
        "source": _src(
            "US Department of Commerce (ITA)", "2023-11-09",
            "https://www.govinfo.gov/content/pkg/FR-2023-11-09/html/2023-24796.htm",
            "Commerce determines that LWRPT completed in Vietnam using China-origin HRS and "
            "subsequently exported from Vietnam to the United States is circumventing the "
            "Orders on a country-wide basis.",
        ),
        "attack": {
            "origin": "Hai Phong Port, Vietnam", "shipper_country": "Vietnam",
            "shipper_company": "Vietnamese steel pipe exporter (named generically)",
            "destination": "Houston, United States", "receiver_country": "United States",
            "receiver_company": "US steel service centre (named generically)",
            "hs_code": "7306.61", "transport_mode": "sea",
            "cargo_description": "Light-walled rectangular steel tube, wall under 4 mm, Vietnam origin",
            "declared_value": 31_000, "weight_kg": 24_000,
        },
        "counterpart": {},
        "assumptions": ["value and weight per container assumed"],
        "booking_shows": "Nothing: the coil's origin is not on a booking.",
    },
    {
        "ref": "EPPO-2024-ALFOIL-DE",
        "typology": "origin_transshipment",
        "title": "Chinese aluminium foil declared as Myanmar origin to avoid EU anti-dumping duty",
        "source": _src(
            "EPPO", "2024-07-29",
            "https://www.eppo.europa.eu/media/news/germany-eppo-brings-charges-against-two-evading-anti-dumping-duties-aluminium-foil-imports-2024-07-29_en",
            "The defendants allegedly declared false goods tariff numbers or a false country of "
            "origin (Myanmar instead of China) to avoid paying anti-dumping duties.",
        ),
        "attack": {
            "origin": "Yangon, Myanmar", "shipper_country": "Myanmar",
            "shipper_company": "Company in Myanmar (unnamed in the release)",
            "destination": "Hamburg, Germany", "receiver_country": "Germany",
            "receiver_company": "German importer (unnamed in the release)",
            "hs_code": "7607.11", "transport_mode": "sea",
            "cargo_description": "Aluminium foil rolls, Myanmar origin",
            "declared_value": 45_000, "weight_kg": 15_000,
        },
        "counterpart": {
            "origin": "Shanghai, China", "shipper_country": "China",
            "shipper_company": "Yangtze Aluminium Foil Co., Ltd.",
            "cargo_description": "Aluminium foil rolls, China origin, anti-dumping duty declared",
        },
        "assumptions": ["value and weight per import assumed"],
        "booking_shows": "An origin country with no known aluminium foil production.",
    },
    {
        "ref": "EPPO-2024-ALSHEETS-ES",
        "typology": "origin_transshipment",
        "title": "Chinese aluminium sheets declared as UAE origin through companies in Spain, Portugal and the UAE",
        "source": _src(
            "EPPO", "2024-12-19",
            "https://www.eppo.europa.eu/media/news/spain-eppo-dismantles-organised-crime-group-evaded-eur33-million-antidumping-duties-2024-12-19_en",
            "declaring their country of origin to be the UAE, when the goods in question "
            "actually originated in China, and were therefore subject to higher customs duties.",
        ),
        "attack": {
            "origin": "Jebel Ali, United Arab Emirates", "shipper_country": "United Arab Emirates",
            "shipper_company": "UAE trading company (unnamed in the release)",
            "destination": "Valencia, Spain", "receiver_country": "Spain",
            "receiver_company": "Spanish importer (unnamed in the release)",
            "hs_code": "7606.12", "transport_mode": "sea",
            "cargo_description": "Aluminium alloy sheets, UAE origin",
            "declared_value": 52_000, "weight_kg": 18_000,
        },
        "counterpart": {
            "origin": "Shanghai, China", "shipper_country": "China",
            "shipper_company": "Huangpu Aluminium Sheet Co., Ltd.",
            "cargo_description": "Aluminium alloy sheets, China origin, anti-dumping duty declared",
        },
        "assumptions": ["value and weight per import assumed"],
        "booking_shows": "A Gulf re-export hub declared as the origin of a metal under EU anti-dumping duty.",
    },

    # ---- misclassification and declared-procedure fraud ----------------
    {
        "ref": "EPPO-2024-STEELSHEETS-ES",
        "typology": "undervaluation_misclassification",
        "title": "Finished Chinese steel sheets declared as semi-finished slabs to avoid anti-dumping duty",
        "source": _src(
            "EPPO", "2024-09-24",
            "https://www.eppo.europa.eu/media/news/spain-five-directors-two-companies-indicted-evading-anti-dumping-duties-steel-sheets-2024-09-24_en",
            "the defendants declared the imported goods as slabs, which are intermediate or "
            "semi-finished iron or steel products with a lower level of processing and rolling "
            "than sheets.",
        ),
        "attack": {
            "origin": "Tianjin, China", "shipper_country": "China",
            "shipper_company": "Chinese steel exporter (unnamed in the release)",
            "destination": "Bilbao, Spain", "receiver_country": "Spain",
            "receiver_company": "Spanish importer (unnamed in the release)",
            "hs_code": "7207.12", "transport_mode": "sea",
            "cargo_description": "Semi-finished steel slabs",
            "declared_value": 400_000, "weight_kg": 600_000,
        },
        "counterpart": {
            "hs_code": "7208.51",
            "cargo_description": "Hot-rolled steel sheets, anti-dumping duty declared",
        },
        "assumptions": ["value and weight per bulk shipment assumed"],
        "booking_shows": "Nothing, if the description repeats the false classification. The goods have to be seen.",
    },
    {
        "ref": "EPPO-2024-EBIKES-BE",
        "typology": "undervaluation_misclassification",
        "title": "Complete Chinese e-bikes imported as separate parts via Antwerp to avoid the anti-dumping duty on assembled e-bikes",
        "source": _src(
            "EPPO", "2024-04-19",
            "https://www.eppo.europa.eu/media/news/belgium-three-convicted-evading-eur31-million-customs-duties-imported-e-bikes-2024-04-19_en",
            "whole e-bikes were deliberately imported in separate parts, to avoid the payment of "
            "anti-dumping duties due on the importation of fully assembled e-bikes.",
        ),
        "attack": {
            "origin": "Ningbo, China", "shipper_country": "China",
            "shipper_company": "Chinese e-bike supplier (unnamed in the release)",
            "destination": "Antwerp, Belgium", "receiver_country": "Belgium",
            "receiver_company": "French importer (unnamed in the release)",
            "hs_code": "8714.10", "transport_mode": "sea",
            "cargo_description": "Bicycle parts: frames, hub motors, batteries, wheels, in matching counts",
            "declared_value": 90_000, "weight_kg": 9_000,
        },
        "counterpart": {
            "hs_code": "8711.60",
            "cargo_description": "Electric bicycles, assembled, anti-dumping duty declared",
        },
        "assumptions": ["value and weight per container assumed", "'matching counts' paraphrases the release's finding that the parts made whole e-bikes"],
        "booking_shows": "Parts in matching counts that together make whole e-bikes.",
    },
    {
        "ref": "OLAF-2026-PL-TRANSIT",
        "typology": "undervaluation_misclassification",
        "title": "Chinese goods entering by rail through Belarus under a T1 transit to Belgium that never left Poland",
        "source": _src(
            "EU OLAF", "2026-04-28",
            "https://anti-fraud.ec.europa.eu/media-corner/news/olaf-plays-central-role-uncovering-major-vat-and-customs-fraud-involving-imports-undeclared-goods-2026-04-28_en",
            "removal of goods from transit procedures through false confirmations of arrival, "
            "misdeclaration of goods to benefit from lower duty rates, abuse of customs "
            "procedure 42 to evade VAT as well as fabrication of transport documents (CMRs)",
            "https://www.eppo.europa.eu/en/media/news/poland-nine-suspects-detained-probe-customs-fraud-linked-to-chinese-imports-polish",
        ),
        "attack": {
            "origin": "Chongqing, China", "shipper_country": "China",
            "shipper_company": "Chinese e-commerce supplier (unnamed in the release)",
            "destination": "Liege, Belgium", "receiver_country": "Belgium",
            "receiver_company": "Shell company, Belgium (unnamed in the release)",
            "hs_code": "6204.62", "transport_mode": "rail",
            "cargo_description": "Women's cotton trousers",
            "declared_value": 40_000, "weight_kg": 8_000,
            "route_details": (
                "Rail Chongqing, China to Malaszewicze, Poland via Brest, Belarus; "
                "T1 transit to Liege, Belgium"
            ),
            "transit_points": "Brest, Belarus; Malaszewicze, Poland",
        },
        "counterpart": {
            "receiver_company": "Liege Fashion Logistics SA",
        },
        "assumptions": ["value and weight per wagon assumed", "textiles stand in for 'textiles, footwear and e-bikes'"],
        "booking_shows": "A rail transit through Belarus. The fraud, goods that never arrive, happens after the booking.",
    },
]


def _defaults(base: dict) -> dict:
    """The neutral fields every shipment carries, overlaid by the case's own."""
    from vf_logistics import verifier

    shipment = {
        "currency": "USD",
        "incoterm": "FCA",
        "transport_mode": "sea",
        "shipper_name": "Export desk",
        "shipper_tax_id": "PUB-0000000000",
        "shipper_tx_count": NEUTRAL_TX_COUNT,
        "receiver_name": "Procurement",
        "transit_points": "none",
    }
    shipment.update(base)
    shipment.setdefault("consignee_name", shipment.get("receiver_company"))
    shipment.setdefault(
        "route_details",
        f"{shipment['origin']} to {shipment['destination']}, direct",
    )
    # Ratio 1.0 against the lane figure verifier.py itself uses, so the freight check
    # cannot fire on a number this script chose.
    baseline, _ = verifier.lane_baseline(shipment)
    shipment["shipping_cost"] = round(baseline, 2)
    shipment["freight_cost"] = shipment["shipping_cost"]
    return shipment


def build() -> dict:
    cases = []
    for n, pair in enumerate(PAIRS, 1):
        attack = _defaults(pair["attack"])
        counterpart = _defaults({**pair["attack"], **pair["counterpart"]})
        # A counterpart whose fields equal the attack's is recorded as such: the two
        # are indistinguishable at booking, which is the finding for that typology.
        identical = {k: v for k, v in attack.items() if k != "shipment_id"} == {
            k: v for k, v in counterpart.items() if k != "shipment_id"
        }
        common = {
            "source_ref": pair["ref"],
            "typology": pair["typology"],
            "title": pair["title"],
            "source": pair["source"],
            "assumptions": pair["assumptions"],
            "booking_shows": pair["booking_shows"],
        }
        attack_id = f"PUB-{n:02d}-A"
        honest_id = f"PUB-{n:02d}-H"
        cases.append({
            "case_id": attack_id, "attack": pair["typology"], "expected_flagged": True,
            "expected_codes": [], **common,
            "shipment": {**attack, "shipment_id": attack_id},
        })
        cases.append({
            "case_id": honest_id, "attack": None, "expected_flagged": False,
            "expected_codes": [],
            # Controlled goods on an honest shipment still want a licence check, so
            # a hold there is defensible; reported apart from the other honest cases.
            "hard_negative": pair["typology"] == "dual_use_transshipment",
            "indistinguishable_from_attack": identical,
            **common,
            "shipment": {**counterpart, "shipment_id": honest_id},
        })

    typologies: dict[str, int] = {}
    for pair in PAIRS:
        typologies[pair["typology"]] = typologies.get(pair["typology"], 0) + 1
    return {
        "meta": {
            "count": len(cases),
            "pairs": len(PAIRS),
            "seed": None,
            "composition": typologies,
            "built_by": "scripts/build_public_cases.py",
            "note": (
                "Each pair is one public enforcement case: the shipment as declared, and "
                "the legitimate trade it imitated. Sources and verbatim quotes are on "
                "every case. Neutral defaults are identical within a pair: "
                f"{NEUTRAL_TX_COUNT} prior shipments, freight at the lane baseline, FCA."
            ),
        },
        "cases": cases,
    }


def main() -> int:
    payload = build()
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    identical = sum(1 for c in payload["cases"] if c.get("indistinguishable_from_attack"))
    print(f"wrote {OUT.relative_to(ROOT)}: {payload['meta']['pairs']} pairs, "
          f"{identical} counterparts identical to their attack at booking")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
