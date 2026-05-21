import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Set

import attrs
from web_poet import HttpClient, Returns, WebPage, field, handle_urls

from funda_listing.items import Address, Agent, PriceInfo, RangeValue, FundaListingItem



DUTCH_TO_ENGLISH: Dict[str, str] = {
    # Build / Construction
    "soort_woonhuis":                       "house_type_detail",
    "soort_appartement":                    "apartment_type_detail",
    "soort_object":                         "object_type_detail",
    "soort_bouw":                           "build_type",           # e.g. bestaande bouw / nieuwbouw
    "bouwjaar":                             "construction_year",
    "bouwvorm":                             "construction_type",
    "bouwperiode":                          "construction_period",
    "dak_type":                             "roof_type",
    "soort_dak":                            "roof_type",
    "dakbedekking":                         "roof_covering",
    "isolatie":                             "insulation",
    "verwarming":                           "heating",
    "warm_water":                           "hot_water",
    "cv_ketel":                             "central_heating_boiler",
    "cv-ketel":                             "central_heating_boiler",
    "energielabel":                         "energy_label",
    "energieklasse":                        "energy_class",
    "beschikbaar_per":                      "available_from",
    "beschikbaar":                          "available",
    "aanvaarding":                          "acceptance",
    "specifieke_indeling":                  "specific_layout",

    # Transfer / Listing
    "aangeboden_sinds":                     "listed_since",
    "vraagprijs":                           "asking_price",
    "vraagprijs_per_m2":                    "asking_price_per_sqm",
    "huurprijs":                            "rent_price",
    "servicekosten":                        "service_costs",
    "bijdrage_vve":                         "hoa_monthly_contribution",
    "opstal_verzekering":                   "building_insurance",
    "waarborgsom":                          "security_deposit",
    "overdrachtsbelasting":                 "transfer_tax",
    "looptijd":                             "contract_duration",
    "huurovereenkomst":                     "rental_agreement_type",
    "soort_eigendom":                       "ownership_type",
    "erfpacht":                             "leasehold",
    "erfpacht_jaarlijkse_canon":            "leasehold_annual_fee",
    "kadastrale_aanduiding":                "cadastral_designation",
    "eigendomssituatie":                    "ownership_situation",
    "permanente_bewoning":                  "permanent_habitation",

    # Area / Layout
    "woonoppervlakte":                      "living_area_sqm",
    "gebruiksoppervlakte":                  "usable_area_sqm",
    "perceeloppervlakte":                   "plot_area_sqm",
    "inhoud":                               "volume_m3",
    "externe_bergruimte":                   "external_storage_sqm",
    "gebouwgebonden_buitenruimte":          "building_outdoor_space_sqm",
    "overige_inpandige_ruimte":             "other_indoor_space_sqm",
    "overige_ruimte":                       "other_space_sqm",
    "aantal_kamers":                        "number_of_rooms",
    "aantal_slaapkamers":                   "number_of_bedrooms",
    "aantal_badkamers":                     "number_of_bathrooms",
    "aantal_woonlagen":                     "number_of_floors",
    "gelegen_op":                           "located_on_floor",
    "woonlagen":                            "residential_floors",
    "badkamer_voorzieningen":               "bathroom_amenities",
    "keuken":                               "kitchen",

    # Outdoor
    "tuin":                                 "garden",
    "tuin_ligging":                         "garden_orientation",
    "achtertuin":                           "back_garden",
    "voortuin":                             "front_garden",
    "zijtuin":                              "side_garden",
    "balkon":                               "balcony",
    "dakterras":                            "rooftop_terrace",
    "terras":                               "terrace",
    "oppervlakte":                          "area_sqm",
    "diepte":                               "depth_m",
    "breedte":                              "width_m",

    # Garage / Parking
    "soort_garage":                         "garage_type",
    "soort_parkeergelegenheid":             "parking_type",
    "capaciteit":                           "capacity",
    "parkeergelegenheid":                   "parking",
    "parkeerfaciliteiten":                  "parking_facilities",

    # Storage
    "bergruimte":                           "storage_space",
    "soort_bergruimte":                     "storage_type",
    "schuur_berging":                       "shed_storage",

    # General / Misc
    "ligging":                              "location_type",
    "voorzieningen":                        "facilities",
    "faciliteiten":                         "amenities",
    "bijzonderheden":                       "special_features",
    "onderhoud_binnen":                     "interior_maintenance",
    "onderhoud_buiten":                     "exterior_maintenance",
    "toegankelijkheid":                     "accessibility",
    "vve_inschrijving_kvk":                 "hoa_registered_chamber_of_commerce",
    "periodieke_bijdrage_vve":              "hoa_periodic_contribution",
    "reservefonds_vve":                     "hoa_reserve_fund",

    # Build extras (seen in sample output)
    "specifiek":                            "specific_features",
    "keurmerken":                           "quality_marks",

    # Outdoor — slash-normalised variants (slash → underscore via _translate_key)
    "balkon_dakterras":                     "balcony_or_rooftop_terrace",
    "schuur_berging":                       "shed_storage",

    # Areas
    "wonen":                                "living_area_sqm",

    # Layout
    "badkamervoorzieningen":                "bathroom_amenities",

    # Transfer / price
    "oorspronkelijke_huurprijs":            "original_rent_price",

    # VvE checklist inner keys
    "inschrijving_kvk":                     "registered_chamber_of_commerce",
    "jaarlijkse_vergadering":               "annual_meeting",
    "periodieke_bijdrage":                  "periodic_contribution",
    "reservefonds_aanwezig":                "reserve_fund_present",
    "onderhoudsplan":                       "maintenance_plan",
    "opstalverzekering":                    "building_insurance",
    "oorspronkelijke_vraagprijs":       "original_asking_price",
    "vraagprijs_per_m2":                "asking_price_per_sqm",
    "ligging_tuin":    "garden_position",
}


SECTION_TITLE_MAP: Dict[str, str] = {
    "bouw":                     "construction",
    "overdracht":               "transfer",
    "indeling":                 "layout",
    "oppervlakten en inhoud":   "areas_and_volume",
    "oppervlakten":             "areas",
    "buitenruimte":             "outdoor_space",
    "bergruimte":               "storage_space",
    "garage":                   "garage",
    "parkeergelegenheid":       "parking",
    "energieklasse":            "energy_class",
    "duurzaamheid":             "sustainability",
    "omschrijving":             "description",
    "kenmerken":                "features",
    "kadastrale informatie":    "cadastral_information",
    "vve":                      "homeowners_association",
    "energie":                  "energy",
    "duurzaamheid":             "sustainability",
    "vve checklist":            "homeowners_association_checklist",
    "vve-checklist":            "homeowners_association_checklist",
    "vve_checklist":            "homeowners_association_checklist",
    "kadastrale gegevens":      "cadastral_information",
}


def _translate_section_title(raw_title: str) -> str:
    """Map a Dutch feature section Title to an English snake_case key."""
    key = raw_title.lower().strip()
    if key in SECTION_TITLE_MAP:
        return SECTION_TITLE_MAP[key]
    # Fallback: snake_case so the format is at least consistent
    return re.sub(r"[\s\-]+", "_", key)


STATUS_MAP: Dict[str, str] = {
    "beschikbaar":                          "available",
    "verkocht":                             "sold",
    "verkocht_onder_voorbehoud":            "sold_under_reservation",
    "onder_bod":                            "under_bid",
    "onder_optie":                          "under_option",
    "verhuurd":                             "rented",
    "verhuurd_onder_voorbehoud":            "rented_under_reservation",
    "geveild":                              "auctioned",
    "ingetrokken":                          "withdrawn",
}


def _translate_key(raw_label: str) -> str:
    """Convert a Dutch feature label to English snake_case key.

    Normalises spaces, hyphens, and forward slashes to underscores before
    the lookup so labels like 'balkon/dakterras' and 'schuur/berging' are
    found in DUTCH_TO_ENGLISH rather than falling through untranslated.
    """
    key = raw_label.lower().replace(" ", "_").replace("-", "_").replace("/", "_")
    key = key.replace("²", "2").replace("³", "3")

    return DUTCH_TO_ENGLISH.get(key, key)



def _split_house_number(raw_hn: str, raw_hs: str):
    hn = (raw_hn or "").strip()
    hs = (raw_hs or "").strip()

    # Both present — remove suffix that may already be appended to hn
    if hn and hs:
        if hn.endswith(" " + hs):
            hn = hn[:-(len(hs) + 1)].strip()
        elif hn.endswith(hs) and hn != hs:
            possible = hn[:-len(hs)].strip()
            if possible and possible[-1].isdigit():
                hn = possible

    # Only hn present — try to split "725A" / "725 A" / "12-B" into parts
    if hn and not hs:
        m = re.match(r"^\s*(\d+)\s*[-\s]*([A-Za-z]\w*)\s*$", hn)
        if m:
            hn, hs = m.group(1).strip(), m.group(2).strip()
        else:
            # numeric suffix requires explicit separator to avoid splitting "288" → "28"+"8"
            m = re.match(r"^\s*(\d+)[-\s]+(\d+\w*)\s*$", hn)
            if m:
                hn, hs = m.group(1).strip(), m.group(2).strip()

    # Normalise suffix: strip leading dashes, uppercase
    if hs:
        hs = hs.lstrip("-").strip().upper()

    return hn, hs


@handle_urls("funda.nl")
@attrs.define
class FundaListingPage(WebPage, Returns[FundaListingItem]):
    http: HttpClient


    @property
    def _nuxt_raw(self) -> List[Any]:
        raw = self.xpath('//script[@id="__NUXT_DATA__"]/text()').get()
        try:
            return json.loads(raw) if raw else []
        except (json.JSONDecodeError, TypeError):
            return []

    def hydrate(self, node: Any, data: List[Any], stack: Set[int] = None) -> Any:
        if stack is None:
            stack = set()

        if node is None or isinstance(node, (str, bool, float)):
            return node

        if isinstance(node, int):
            if node == -1:
                return None
            if 0 <= node < len(data):
                if node in stack:
                    return None
                stack.add(node)
                result = self.hydrate(data[node], data, stack)
                stack.remove(node)
                return result
            return node

        if isinstance(node, list):
            if len(node) == 2 and isinstance(node[0], str) and isinstance(node[1], int):
                return self.hydrate(node[1], data, stack)
            return [self.hydrate(x, data, stack) for x in node]

        if isinstance(node, dict):
            return {k: self.hydrate(v, data, stack) for k, v in node.items()}

        return node

    @property
    def nuxt_data(self) -> Dict[str, Any]:
        data = self._nuxt_raw
        if not data:
            return {}

        for item in data:
            if isinstance(item, dict):
                idx = item.get("cachedProjectData_nl") or item.get("cachedListingData_nl")
                if isinstance(idx, int) and 0 <= idx < len(data):
                    return self.hydrate(data[idx], data) or {}
        return {}

    # -----------------------------------------------------------------------
    # Basic fields
    # -----------------------------------------------------------------------

    @field
    def id(self) -> Optional[int]:
        return self.nuxt_data.get("globalId")

    @field
    def status(self) -> str:
        """Requirement #5 — map Dutch status to English granular value."""
        raw = (
            self.nuxt_data.get("tracking", {}).get("listing_status", "") or ""
        ).lower().strip()
        return STATUS_MAP.get(raw, raw)

    @field
    def listing_category(self) -> str:
        """Requirement #2 — derive buy / rent / new from scraped data."""
        if self.construction_type and "nieuw" in self.construction_type.lower():
            return "new"
        ot = (self.offering_type or "").lower()
        if "huur" in ot or "rent" in ot:
            return "rent"
        return "buy"

    @field
    def object_detail_page_relative_url(self) -> str:
        return self.nuxt_data.get("friendlyUrlSlug", "") or ""

    @field
    def full_description(self) -> str:
        return self.nuxt_data.get("description", {}).get("content") or ""

    # -----------------------------------------------------------------------
    # Requirement #3 — Address with house_number_suffix as distinct top-level key
    # -----------------------------------------------------------------------

    @field
    def address(self) -> Address:
        data = self.nuxt_data
        raw = data.get("address") or {}
        targeting = data.get("advertising", {}).get("targetingOptions", {})


        raw_hn = str(raw.get("houseNumber") or "").strip()
        raw_hs = str(raw.get("houseNumberSuffix") or "").strip()  # ← fix: was missing

        h_num, h_suffix = _split_house_number(raw_hn, raw_hs)


        title = raw.get("addressTitle") or ""

        if title:
            street = re.sub(
                r"\s+" + re.escape(h_num) + r"(?:[-\s]*\w+)?\s*$",
                "",
                title,
            ).strip()
        else:
            street = ""

        return Address(
            city=raw.get("city") or "",
            country=raw.get("country") or "",
            province=raw.get("province") or "",
            postal_code=raw.get("postcode") or "",
            house_number=h_num,
            house_number_suffix=h_suffix,
            street_name=street,
            municipality=targeting.get("gemeente") or "",
            wijk=raw.get("city") or "",
            neighbourhood=(
                raw.get("neighborhood", {}).get("name")
                if isinstance(raw.get("neighborhood"), dict)
                else ""
            ) or "",
            is_bag_address=True,
            identifiers=[
                str(val).lower()
                for key, val in raw.items()
                if not isinstance(val, (dict, bool, list)) and val is not None
            ],
        )



    @field
    def number_of_bedrooms(self) -> Optional[int]:
        val = self.nuxt_data.get("featuresFastView", {}).get("numberOfBedrooms")
        try:
            return int(val) if val is not None else None
        except (ValueError, TypeError):
            return None

    def _parse_m2(self, raw: Any) -> Optional[int]:
        if not raw or not isinstance(raw, str):
            return None
        match = re.search(r"(\d+)", raw.replace(".", ""))
        if match:
            try:
                return int(match.group(1))
            except (ValueError, TypeError):
                return None
        return None

    @field
    def plot_area_range(self) -> RangeValue:
        val = self._parse_m2(
            self.nuxt_data.get("featuresFastView", {}).get("plotArea")
        )
        return RangeValue(gte=val, lte=val) if val else RangeValue(gte=0, lte=0)

    @field
    def floor_area_range(self) -> RangeValue:
        val = self._parse_m2(
            self.nuxt_data.get("featuresFastView", {}).get("livingArea")
        )
        return RangeValue(gte=val, lte=val) if val else RangeValue(gte=0, lte=0)

    @field
    def floor_area(self) -> List[int]:
        val = self.floor_area_range.gte
        return [val] if val and val > 0 else []

    @field
    def plot_area(self) -> List[int]:
        val = self.plot_area_range.gte
        return [val] if val and val > 0 else []

    @field
    def number_of_rooms(self) -> Optional[int]:
        val = (
            self.nuxt_data.get("advertising", {})
            .get("targetingOptions", {})
            .get("aantalkamers")
        )
        try:
            return int(val) if val is not None else None
        except (ValueError, TypeError):
            return None


    @field
    def object_type(self) -> str:
        return self.nuxt_data.get("objectType") or ""

    @field
    def energy_label(self) -> str:
        return self.nuxt_data.get("featuresFastView", {}).get("energyLabel") or ""

    @field
    def construction_type(self) -> str:
        return (
            self.nuxt_data.get("advertising", {})
            .get("targetingOptions", {})
            .get("bouwvorm") or ""
        )

    @field
    def offering_type(self) -> str:
        return self.nuxt_data.get("offeringType") or ""

    @field
    def zoning(self) -> str:
        targeting = self.nuxt_data.get("advertising", {}).get("targetingOptions", {})
        is_commercial = str(targeting.get("bedrijfsruimte", "")).lower() == "true"
        return "commercial" if is_commercial else "residential"

    @field
    def publish_date(self) -> str:
        return self.nuxt_data.get("publicationDate") or ""


    @field
    def thumbnail_id(self) -> List[str]:
        media_items = (
            self.nuxt_data.get("media", {}).get("photos", {}).get("items", []) or []
        )
        return [
            str(photo.get("id", "")).replace("/", "")
            for photo in media_items
            if photo.get("id")
        ]

    @field
    def image_urls(self) -> List[str]:
        """Requirement #1 — full valentina_media URLs built from thumbnail IDs."""
        urls = []
        for tid in self.thumbnail_id:
            try:
                s = str(tid).zfill(9)
                urls.append(
                    f"https://cloud.funda.nl/valentina_media/{s[:3]}/{s[3:6]}/{s[6:]}.jpg"
                )
            except Exception:
                pass
        return urls



    @field
    def available_media_types(self) -> List[str]:
        media = self.nuxt_data.get("media", {})
        return [k for k, v in media.items() if k != "layout" and v]

    @field
    def product_entitlement(self) -> List[str]:
        data = self.nuxt_data
        media = data.get("media", {})
        toggles = data.get("state", {}).get("$sfeatureToggles", {})
        promo = data.get("promo", {})

        entitlements = []
        mapping = {
            "floorplan":     media.get("floorPlan") or media.get("legacyFloorPlan"),
            "brochure":      media.get("brochureUrl"),
            "video":         media.get("videos"),
            "photo_360":     media.get("photos360") or media.get("legacyPhotos360"),
            "virtual_tour":  media.get("virtualTour"),
        }
        for key, exists in mapping.items():
            if exists:
                entitlements.append(key)

        if toggles.get("ShowListingHighlights"):
            entitlements.append("highlights")
        if promo.get("blikvanger"):
            entitlements.append("featured")

        return entitlements

    @field
    def blikvanger(self) -> dict:
        promo_data = self.nuxt_data.get("promo", {}).get("blikvanger")
        if promo_data:
            text = promo_data.get("text", "") if isinstance(promo_data, dict) else ""
            return {"text": text or "", "enabled": True}
        return {"text": "", "enabled": False}


    @field
    def price(self) -> PriceInfo:
        raw = self.nuxt_data.get("price", {}) or {}

        selling_text = raw.get("sellingPrice") or ""
        rental_text  = raw.get("rentalPrice")  or ""

        def _extract_prices(text: str) -> List[int]:
            clean = text.replace(".", "")
            return [int(n) for n in re.findall(r"\d+", clean)]

        def _extract_condition(text: str) -> str:
            low = text.lower()
            if "k.k." in low:
                return "kosten koper"
            if "v.o.n." in low:
                return "vrij op naam"
            return ""

        selling_prices = _extract_prices(selling_text)
        rent_prices    = _extract_prices(rental_text)

        s_range = RangeValue(gte=min(selling_prices), lte=max(selling_prices)) if selling_prices else None
        r_range = RangeValue(gte=min(rent_prices), lte=max(rent_prices)) if rent_prices else None

        is_rent = bool(rental_text and not selling_text)

        return PriceInfo(
            selling_price=selling_prices,
            selling_price_range=s_range,
            selling_price_type="" if is_rent else "sale",
            selling_price_condition="" if is_rent else _extract_condition(selling_text),
            rent_price=rent_prices,
            rent_price_range=r_range,
            rent_price_type="rent" if is_rent else "",
            rent_price_condition=_extract_condition(rental_text) if is_rent else "",
        )


    @field
    async def agents(self) -> List[Dict[str, Any]]:
        return await self.get_broker_details()

    async def get_broker_details(self) -> List[Dict[str, Any]]:
        data_str = json.dumps(self.nuxt_data)
        pattern = r'broker_?id(?:["\']:\s*["\']|[:=])(\d+)'
        found_ids = set(re.findall(pattern, data_str, re.IGNORECASE))

        if not found_ids:
            return []

        tasks = [self.fetch_single_broker(b_id) for b_id in found_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if isinstance(r, dict) and r]

    async def fetch_single_broker(self, b_id: str) -> Dict[str, Any]:
        url = f"https://www.funda.nl/makelaar/{b_id}/"
        try:
            response = await self.http.get(url)
            script_text = response.xpath('//script[@id="__NUXT_DATA__"]/text()').get()
            if not script_text:
                return {}

            broker_raw_list = json.loads(script_text)
            blueprint = next(
                (
                    item
                    for item in broker_raw_list
                    if isinstance(item, dict)
                    and "officeId" in item
                    and "displayName" in item
                ),
                None,
            )

            if not blueprint:
                return {}

            resolved = self.hydrate(blueprint, broker_raw_list)

            logo_id_str = ""
            logo_url_str = ""
            srcset = response.xpath(
                '//picture/img[contains(@alt, "Logo")]/@srcset'
            ).get()
            if srcset and "valentina_media/" in srcset:
                try:
                    raw_id = (
                        srcset.split("valentina_media/")[1]
                        .split(".")[0]
                        .replace("/", "")
                    )
                    logo_id_str = raw_id
                    s = str(raw_id).zfill(9)
                    logo_url_str = (
                        f"https://cloud.funda.nl/valentina_media"
                        f"/{s[:3]}/{s[3:6]}/{s[6:]}.jpg"
                    )
                except (IndexError, ValueError):
                    pass

            o_id = resolved.get("officeId")
            final_office_id = o_id.get("id") if isinstance(o_id, dict) else o_id
            is_primary = (
                str(self.nuxt_data.get("tracking", {}).get("main_broker_id")) == b_id
            )

            return {
                "id":           b_id,
                "office_id":    str(final_office_id) if final_office_id else "",
                "relative_url": f"/makelaar/{b_id}/",
                "is_primary":   is_primary,
                "logo_id":      logo_id_str,
                "logo_url":     logo_url_str,
                "name":         resolved.get("displayName") or "",
                "association":  resolved.get("affiliation") or "",
            }
        except Exception:
            return {}


    @field
    def build(self) -> Dict[str, Any]:
        features = self.nuxt_data.get("features") or []
        section = next((f for f in features if f.get("Id") == "bouw"), {})
        return {
            _translate_key(item.get("Label", "")): item.get("Value") or ""
            for item in section.get("KenmerkenList", [])
            if item.get("Label") and item.get("Value")
        }

    @field
    def amenities(self) -> List[str]:
        features = self.nuxt_data.get("features") or []
        indeling = next((f for f in features if f.get("Id") == "indeling"), {})
        kenmerken = indeling.get("KenmerkenList", [])

        raw_amenities = next(
            (
                item.get("Value")
                for item in kenmerken
                if item.get("Id") == "indeling-generalfacilities"
            ),
            "",
        )

        if raw_amenities:
            return [
                a.strip().lower()
                for a in raw_amenities.replace(" en ", ", ").split(",")
                if a.strip()
            ]
        return []

    @field
    def outdoor_space(self) -> Dict[str, Any]:
        features = self.nuxt_data.get("features") or []
        section = next((f for f in features if f.get("Id") == "buitenruimte"), {})
        return {
            _translate_key(item.get("Label", "")): item.get("Value") or ""
            for item in section.get("KenmerkenList", [])
            if item.get("Label") and item.get("Value")
        }

    @field
    def garden_location(self) -> Dict[str, Any]:
        features = self.nuxt_data.get("features") or []
        section = next((f for f in features if f.get("Id") == "buitenruimte"), {})
        return {
            _translate_key(item.get("Label", "")): item.get("Value") or ""
            for item in section.get("KenmerkenList", [])
            if item.get("Label")
            and item.get("Value")
            and "ligging" in item.get("Id", "").lower()
        }

    @field
    def storage_space(self) -> Dict[str, Any]:
        features = self.nuxt_data.get("features") or []
        section = next((f for f in features if f.get("Id") == "bergruimte"), {})
        return {
            _translate_key(item.get("Label", "")): item.get("Value") or ""
            for item in section.get("KenmerkenList", [])
            if item.get("Label") and item.get("Value")
        }

    @field
    def garage(self) -> Dict[str, Any]:
        features = self.nuxt_data.get("features") or []
        section = next(
            (f for f in features if "garage" in f.get("Id", "").lower()), {}
        )
        return {
            _translate_key(item.get("Label", "")): item.get("Value") or ""
            for item in section.get("KenmerkenList", [])
            if item.get("Label") and item.get("Value")
        }

    @field
    def parking(self) -> Dict[str, Any]:
        features = self.nuxt_data.get("features") or []
        section = next(
            (f for f in features if f.get("Id") == "parkeergelegenheid"), {}
        )
        return {
            _translate_key(item.get("Label", "")): item.get("Value") or ""
            for item in section.get("KenmerkenList", [])
            if item.get("Label") and item.get("Value")
        }

    @field
    def feature(self) -> Dict[str, Any]:
        """Full nested feature map with English-translated keys.

        Both the section (category) key and each individual field key are
        translated to English snake_case via their respective maps.
        Dutch property descriptions/values are left untouched.
        """
        nested_features: Dict[str, Any] = {}
        raw_features = self.nuxt_data.get("features") or []

        for section in raw_features:
            raw_title = section.get("Title")
            if not raw_title:
                continue

            # Translate the outer section title (e.g. "Overdracht" -> "transfer")
            section_key = _translate_section_title(raw_title)

            category_data: Dict[str, Any] = {}
            for item in section.get("KenmerkenList", []):
                if item.get("KenmerkenList"):
                    for sub_item in item["KenmerkenList"]:
                        label = sub_item.get("Label")
                        value = sub_item.get("Value")
                        if label and value:
                            category_data[_translate_key(label)] = value
                else:
                    label = item.get("Label")
                    value = item.get("Value")
                    if label and value:
                        category_data[_translate_key(label)] = value

            if category_data:
                # Merge if Funda emits duplicate section titles
                if section_key in nested_features:
                    nested_features[section_key].update(category_data)
                else:
                    nested_features[section_key] = category_data

        return nested_features