import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import attrs
from web_poet import Returns, WebPage, field, handle_urls

from funda_listing.immoweb_items import (
    Address,
    Agent,
    Document,
    Image,
    ImmowebListingItem,
    PriceInfo,
    RangeValue,
)


def _g(d: Any, *path: str, default=None):
    for k in path:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
        if d is None:
            return default
    return d


def _extract_js_object(html: str, marker: str) -> Optional[str]:
    """Return the full `{...}` literal assigned at `marker`, brace-balanced.

    The previous non-greedy regex (`\\{.*?\\}`) stopped at the first `};` in
    the document. That happens to land correctly on most pages, but any `};`
    inside a description string truncates the payload and the whole record
    silently degrades to `{}`. Counting braces while respecting string
    literals and escapes is the only safe way to do this.
    """
    i = html.find(marker)
    if i == -1:
        return None
    start = html.find("{", i)
    if start == -1:
        return None

    depth = 0
    in_str = False
    escaped = False
    for k in range(start, len(html)):
        c = html[k]
        if in_str:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return html[start : k + 1]
    return None


# property.type -> broad zoning bucket. Previously hardcoded to "residential",
# which mislabelled every office, warehouse, garage and plot of land.
_ZONING_BY_TYPE = {
    "HOUSE": "residential",
    "APARTMENT": "residential",
    "APARTMENT_GROUP": "residential",
    "HOUSE_GROUP": "residential",
    "NEW_REAL_ESTATE_PROJECT_APARTMENTS": "residential",
    "NEW_REAL_ESTATE_PROJECT_HOUSES": "residential",
    "OFFICE": "commercial",
    "BUSINESS": "commercial",
    "INDUSTRY": "industrial",
    "GARAGE": "parking",
    "LAND": "land",
}


@handle_urls("immoweb.be")
@attrs.define
class ImmowebListingPage(WebPage, Returns[ImmowebListingItem]):

    @property
    def classified(self) -> Dict[str, Any]:
        blob = _extract_js_object(self.html, "window.classified")
        if not blob:
            return {}
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            return {}

    @property
    def _property(self) -> Dict[str, Any]:
        return self.classified.get("property") or {}

    @property
    def _transaction(self) -> Dict[str, Any]:
        return self.classified.get("transaction") or {}

    @property
    def _pictures(self) -> List[Dict[str, Any]]:
        media = self.classified.get("media") or {}
        return [p for p in (media.get("pictures") or []) if isinstance(p, dict)]

    @property
    def _documents(self) -> List[Dict[str, Any]]:
        """`media.documents` is a dict keyed by hash on some pages and an
        (often empty) list on others. Normalise both to a list."""
        docs = (self.classified.get("media") or {}).get("documents")
        if isinstance(docs, dict):
            return [v for v in docs.values() if isinstance(v, dict)]
        if isinstance(docs, list):
            return [v for v in docs if isinstance(v, dict)]
        return []

    @property
    def _is_rent(self) -> bool:
        return (self._transaction.get("type") or "").upper() == "FOR_RENT"

    # -- provenance ---------------------------------------------------------

    @field
    def url(self) -> str:
        return str(self.response.url)

    @field
    def scraped_at(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    # -- basic fields ---------------------------------------------------

    @field
    def id(self) -> Optional[int]:
        return self.classified.get("id")

    @field
    def status(self) -> str:
        flags = self.classified.get("flags") or {}
        if flags.get("isSoldOrRented"):
            return "sold"
        if flags.get("isUnderOption"):
            return "under_option"
        return "available"

    @field
    def listing_category(self) -> str:
        flags = self.classified.get("flags") or {}
        if self._is_rent:
            return "rent"
        if flags.get("isNewlyBuilt"):
            return "new"
        return "buy"

    @field
    def publish_date(self) -> str:
        return _g(self.classified, "publication", "creationDate", default="") or ""

    @field
    def last_modified_date(self) -> str:
        return _g(self.classified, "publication", "lastModificationDate", default="") or ""

    @field
    def expiration_date(self) -> str:
        return _g(self.classified, "publication", "expirationDate", default="") or ""

    @field
    def object_type(self) -> str:
        return self._property.get("type") or ""

    @field
    def object_subtype(self) -> str:
        return self._property.get("subtype") or ""

    @field
    def title(self) -> str:
        return self._property.get("title") or ""

    @field
    def external_reference(self) -> str:
        return str(self.classified.get("externalReference") or "")

    @field
    def offering_type(self) -> str:
        return (self._transaction.get("type") or "").upper()

    @field
    def construction_type(self) -> str:
        """Was reading `building.condition` (GOOD / JUST_RENOVATED), which is
        the condition, not the construction type. Condition now has its own
        field below."""
        return _g(self._property, "constructionPermit", "constructionType", default="") or ""

    @field
    def building_condition(self) -> str:
        return _g(self._property, "building", "condition", default="") or ""

    @field
    def zoning(self) -> str:
        """DERIVED, not an immoweb field — a broad bucket mapped from
        property.type via _ZONING_BY_TYPE. For immoweb's actual planning
        designation see feature.urban_development_zoning."""
        return _ZONING_BY_TYPE.get((self._property.get("type") or "").upper(), "other")

    @field
    def full_description(self) -> str:
        return self._property.get("description") or ""

    @field
    def description_fr(self) -> str:
        return _g(self._property, "alternativeDescriptions", "fr", default="") or ""

    @field
    def description_nl(self) -> str:
        return _g(self._property, "alternativeDescriptions", "nl", default="") or ""

    # -- media ------------------------------------------------------------

    @field
    def image_urls(self) -> List[str]:
        """Prefer `extralargeUrl` (2560x1440) over `largeUrl` (736x736)."""
        urls = [
            p.get("extralargeUrl") or p.get("largeUrl") or p.get("mediumUrl") or p.get("smallUrl")
            for p in self._pictures
        ]
        return [u for u in urls if u]

    @field
    def thumbnail_id(self) -> List[str]:
        """Pictures carry no `id` key at all, so the old `p.get("id")` made
        this list unconditionally empty. The per-image hash in the filename
        is the stable identifier immoweb actually uses."""
        ids = []
        for u in self.image_urls:
            base = os.path.basename(u.split("?")[0])
            stem = os.path.splitext(base)[0]
            if stem:
                ids.append(stem)
        return ids

    @field
    def available_media_types(self) -> List[str]:
        media = self.classified.get("media") or {}
        types = []
        if self._pictures:
            types.append("photo")
        for key, label in (
            ("virtualTourUrl", "virtual_tour"),
            ("virtualExperienceUrl", "virtual_experience"),
            ("externalVideoUrl", "video"),
            ("floorPlans", "floor_plan"),
            ("legalDocuments", "legal_document"),
            ("specifications", "specification"),
        ):
            if media.get(key):
                types.append(label)
        if self._documents:
            types.append("document")
        return types

    @field
    def documents(self) -> List[Document]:
        return [
            Document(
                id=str(d.get("id") or ""),
                type=d.get("type") or "",
                url=d.get("url") or "",
                original_name=d.get("originalName") or "",
                # immoweb wraps this value in literal quote characters.
                hash=str(d.get("hash") or "").strip('"'),
            )
            for d in self._documents
        ]

    @field
    def cluster(self) -> Optional[Dict[str, Any]]:
        cluster = self.classified.get("cluster")
        return cluster if isinstance(cluster, dict) else None

    @field
    def images(self) -> List[Image]:
        return [
            Image(
                small_url=p.get("smallUrl") or "",
                medium_url=p.get("mediumUrl") or "",
                large_url=p.get("largeUrl") or "",
                extralarge_url=p.get("extralargeUrl") or "",
                is_vertical=p.get("isVertical"),
            )
            for p in self._pictures
        ]

    # -- address / agents / price ------------------------------------------

    @field
    def address(self) -> Address:
        loc = _g(self._property, "location", default={}) or {}
        return Address(
            country=loc.get("country") or "",
            province=loc.get("province") or "",
            city=loc.get("locality") or "",
            municipality=loc.get("district") or "",
            street_name=loc.get("street") or "",
            house_number=str(loc.get("number") or ""),
            house_number_suffix=str(loc.get("box") or ""),
            postal_code=str(loc.get("postalCode") or ""),
            # `placeName` is null on essentially every listing. It previously
            # fell back to `district`, which just echoed `municipality` on 69%
            # of rows — a filled-looking column carrying no information. Left
            # empty when immoweb has no real neighbourhood.
            neighbourhood=loc.get("placeName") or "",
            wijk=loc.get("region") or "",
            latitude=loc.get("latitude"),
            longitude=loc.get("longitude"),
            region_code=loc.get("regionCode") or "",
            floor=loc.get("floor"),
            has_sea_view=loc.get("hasSeaView"),
            is_approximated=loc.get("approximated"),
            property_name=loc.get("propertyName") or "",
            location_type=loc.get("type") or "",
        )

    @field
    def agents(self) -> List[Agent]:
        agents = []
        for cust in self.classified.get("customers") or []:
            if not isinstance(cust, dict):
                continue
            oloc = cust.get("location") or {}
            rep = cust.get("salesRepresentative") or {}
            agents.append(
                Agent(
                    id=str(cust.get("id") or ""),
                    name=cust.get("name") or "",
                    office_id=str(cust.get("ipiNo") or ""),
                    association=cust.get("type") or "",
                    relative_url=cust.get("website") or "",
                    logo_url=cust.get("logoUrl") or "",
                    is_primary=bool(cust.get("isOwner")),
                    email=cust.get("email") or "",
                    phone=cust.get("phoneNumber") or "",
                    mobile=cust.get("mobileNumber") or "",
                    ipi_number=str(cust.get("ipiNo") or ""),
                    year_of_foundation=cust.get("yearOfFoundation"),
                    office_street=oloc.get("street") or "",
                    office_postal_code=str(oloc.get("postalCode") or ""),
                    office_city=oloc.get("locality") or "",
                    office_country=oloc.get("country") or "",
                    office_province=oloc.get("province") or "",
                    office_district=oloc.get("district") or "",
                    office_latitude=oloc.get("latitude"),
                    office_longitude=oloc.get("longitude"),
                    contact_hours_landline=cust.get("contactHoursLandline"),
                    contact_hours_mobile=cust.get("contactHoursMobile"),
                    sales_rep_name=rep.get("name") or "",
                    sales_rep_email=rep.get("email") or "",
                    sales_rep_phone=rep.get("landLine") or rep.get("mobile") or "",
                    number_of_active_projects=cust.get("numberOfActiveProjects"),
                    number_of_projects_sold=cust.get("numberOfProjectsSold"),
                    features=cust.get("features") or {},
                )
            )
        return agents

    @field
    def price(self) -> PriceInfo:
        price = self.classified.get("price") or {}
        sale = self._transaction.get("sale") or {}
        rental = self._transaction.get("rental") or {}
        main = price.get("mainValue")
        is_rent = self._is_rent

        selling = None if is_rent else (sale.get("price") or main)
        renting = (rental.get("monthlyRentalPrice") or main) if is_rent else None

        return PriceInfo(
            selling_price=[selling] if selling else [],
            selling_price_type="sale" if selling else "",
            selling_price_condition="vat" if sale.get("isSubjectToVat") else "",
            rent_price=[renting] if renting else [],
            rent_price_type="rent" if renting else "",
            display_price=price.get("mainDisplayPrice") or "",
            main_value=main,
            old_value=price.get("oldValue") or sale.get("oldPrice"),
            old_display_price=price.get("oldDisplayPrice") or "",
            price_per_sqm=sale.get("pricePerSqm"),
            min_range_value=price.get("minRangeValue"),
            max_range_value=price.get("maxRangeValue"),
            is_price_hidden=price.get("hidePrice"),
            has_starting_price=sale.get("hasStartingPrice"),
            monthly_costs=self._property.get("monthlyCosts"),
            cadastral_income=sale.get("cadastralIncome"),
            transaction_subtype=self._transaction.get("subtype") or "",
            price_label=price.get("label") or "",
            price_type=price.get("type") or "",
            html_display_price=price.get("HTMLDisplayPrice") or "",
            short_display_price=price.get("shortDisplayPrice") or "",
            accessibility_price=price.get("accessibilityPrice") or "",
            alternative_display_price=price.get("alternativeDisplayPrice") or "",
            language=price.get("language") or "",
        )

    # -- rooms / areas ------------------------------------------------------

    @property
    def _derived_room_count(self) -> Optional[int]:
        prop = self._property
        parts = [
            prop.get("bedroomCount"),
            prop.get("bathroomCount"),
            prop.get("showerRoomCount"),
            1 if prop.get("hasLivingRoom") else None,
            1 if prop.get("hasDiningRoom") else None,
        ]
        total = sum(p for p in parts if isinstance(p, int))
        return total or None

    @field
    def number_of_rooms(self) -> Optional[int]:
        """Sum of the individual room counts immoweb publishes.

        Deliberately NOT `property.roomCount`. That field is null on ~95% of
        listings and, where it is set, means something else entirely — a
        verified 4-bedroom 211 m² apartment carries roomCount=1, and immoweb's
        own page never renders a "number of rooms" figure. Mixing the two
        produced rows where number_of_rooms < number_of_bedrooms.

        immoweb's raw value is preserved as feature.immoweb_room_count so
        nothing is lost; this column is one consistent thing, a derived total.
        """
        return self._derived_room_count

    @field
    def number_of_bedrooms(self) -> Optional[int]:
        return self._property.get("bedroomCount")

    @field
    def number_of_bathrooms(self) -> Optional[int]:
        return self._property.get("bathroomCount")

    @field
    def number_of_toilets(self) -> Optional[int]:
        return self._property.get("toiletCount")

    @field
    def number_of_shower_rooms(self) -> Optional[int]:
        return self._property.get("showerRoomCount")

    @field
    def energy_label(self) -> str:
        return _g(self._transaction, "certificates", "epcScore", default="") or ""

    @field
    def floor_area_range(self) -> RangeValue:
        living = self._property.get("netHabitableSurface")
        return RangeValue(gte=living, lte=living) if living else RangeValue()

    @field
    def floor_area(self) -> List[int]:
        val = self.floor_area_range.gte
        return [val] if val else []

    @field
    def plot_area_range(self) -> RangeValue:
        """Strictly `property.land.surface` (null for most apartments).

        This used to fall back to `totalBuildableGroundFloorSurface`, which is
        the buildable footprint, not the plot — a different measurement. That
        value is still available as feature.total_buildable_ground_floor_surface.
        """
        plot = _g(self._property, "land", "surface")
        return RangeValue(gte=plot, lte=plot) if plot else RangeValue()

    @field
    def plot_area(self) -> List[int]:
        val = self.plot_area_range.gte
        return [val] if val else []

    # -- full feature bag ---------------------------------------------------

    @field
    def feature(self) -> Dict[str, Any]:
        """Flat snake_case bag. Every key that existed before is still here
        with the same name and meaning; the rest is what used to be dropped."""
        prop = self._property
        txn = self._transaction
        building = prop.get("building") or {}
        energy = prop.get("energy") or {}
        kitchen = prop.get("kitchen") or {}
        permit = prop.get("constructionPermit") or {}
        certs = txn.get("certificates") or {}
        pcerts = prop.get("propertyCertificates") or {}
        spec = prop.get("specificities") or {}
        investor = txn.get("investor") or {}
        sale = txn.get("sale") or {}
        rental = txn.get("rental") or {}
        stats = self.classified.get("statistics") or {}
        flags = self.classified.get("flags") or {}
        pub = self.classified.get("publication") or {}

        bedrooms = [b for b in (prop.get("bedrooms") or []) if isinstance(b, dict)]

        return {
            # --- original keys, unchanged names ---
            "construction_year": building.get("constructionYear"),
            "facade_count": building.get("facadeCount"),
            "has_garden": prop.get("hasGarden"),
            "garden_surface": prop.get("gardenSurface"),
            "has_lift": prop.get("hasLift"),
            "has_basement": prop.get("hasBasement"),
            "parking_indoor": prop.get("parkingCountIndoor"),
            "parking_outdoor": prop.get("parkingCountOutdoor"),
            "kitchen_type": kitchen.get("type"),
            "heating_type": energy.get("heatingType"),
            "epc_consumption_per_sqm": certs.get("primaryEnergyConsumptionPerSqm"),
            "flood_zone": permit.get("floodZoneType"),
            # --- building ---
            # building_condition, monthly_costs, cadastral_income and
            # price_per_sqm are not repeated here — they are top-level
            # (building_condition) or on the price block, and duplicating them
            # invites the two copies to drift apart.
            "floor_count": building.get("floorCount"),
            "annex_count": building.get("annexCount"),
            "street_facade_width": building.get("streetFacadeWidth"),
            "is_heritage_protected": building.get("isHeritageProtected"),
            "has_syndicator": building.get("hasSyndicator"),
            "shared_spaces": building.get("sharedSpaces"),
            # --- surfaces ---
            "net_habitable_surface": prop.get("netHabitableSurface"),
            "land_surface": _g(prop, "land", "surface"),
            "terrace_surface": prop.get("terraceSurface"),
            "terrace_orientation": prop.get("terraceOrientation"),
            "garden_orientation": prop.get("gardenOrientation"),
            "kitchen_surface": kitchen.get("surface"),
            "living_room_surface": _g(prop, "livingRoom", "surface"),
            "dining_room_surface": _g(prop, "diningRoom", "surface"),
            "bedroom_surface": prop.get("bedroomSurface"),
            "bedroom_surfaces": [b.get("surface") for b in bedrooms if b.get("surface")],
            "basement_surface": _g(prop, "basement", "surface"),
            "attic_surface": _g(prop, "attic", "surface"),
            "laundry_room_surface": _g(prop, "laundryRoom", "surface"),
            # --- counts ---
            # immoweb's own roomCount, unmodified. Semantics are unclear (a
            # 4-bedroom flat can carry roomCount=1 and the site never displays
            # it), so it is kept separate from the derived number_of_rooms
            # rather than mixed into it.
            "immoweb_room_count": prop.get("roomCount"),
            "derived_room_count": self._derived_room_count,
            "toilet_count": prop.get("toiletCount"),
            "shower_room_count": prop.get("showerRoomCount"),
            "fireplace_count": prop.get("fireplaceCount"),
            "habitable_unit_count": prop.get("habitableUnitCount"),
            "parking_closed_box": prop.get("parkingCountClosedBox"),
            # --- amenity booleans ---
            "has_terrace": prop.get("hasTerrace"),
            "has_balcony": prop.get("hasBalcony"),
            "has_attic": prop.get("hasAttic"),
            "has_living_room": prop.get("hasLivingRoom"),
            "has_dining_room": prop.get("hasDiningRoom"),
            "has_dressing_room": prop.get("hasDressingRoom"),
            "has_laundry_room": prop.get("hasLaundryRoom"),
            "has_office": spec.get("hasOffice"),
            "has_swimming_pool": prop.get("hasSwimmingPool"),
            "has_sauna": prop.get("hasSauna"),
            "has_jacuzzi": prop.get("hasJacuzzi"),
            "has_hammam": prop.get("hasHammam"),
            "has_fitness_room": prop.get("hasFitnessRoom"),
            "has_tennis_court": prop.get("hasTennisCourt"),
            "has_barbecue": prop.get("hasBarbecue"),
            "has_air_conditioning": prop.get("hasAirConditioning"),
            "has_armored_door": prop.get("hasArmoredDoor"),
            "has_secure_access_alarm": prop.get("hasSecureAccessAlarm"),
            "has_visiophone": prop.get("hasVisiophone"),
            "has_door_phone": prop.get("hasDoorPhone"),
            "has_internet": prop.get("hasInternet"),
            "has_cable_tv": prop.get("hasCableTV"),
            "has_disabled_access": prop.get("hasDisabledAccess"),
            "has_caretaker_or_concierge": prop.get("hasCaretakerOrConcierge"),
            "has_fireplace": prop.get("fireplaceExists"),
            "is_first_occupation": prop.get("isFirstOccupation"),
            "is_holiday_property": prop.get("isHolidayProperty"),
            # --- kitchen appliances ---
            "kitchen_has_oven": kitchen.get("hasOven"),
            "kitchen_has_steam_oven": kitchen.get("hasSteamOven"),
            "kitchen_has_microwave": kitchen.get("hasMicroWaveOven"),
            "kitchen_has_fridge": kitchen.get("hasFridge"),
            "kitchen_has_freezer": kitchen.get("hasFreezer"),
            "kitchen_has_dishwasher": kitchen.get("hasDishwasher"),
            "kitchen_has_washing_machine": kitchen.get("hasWashingMachine"),
            # --- energy ---
            "energy_performance": energy.get("performance"),
            "has_double_glazing": energy.get("hasDoubleGlazing"),
            "has_heat_pump": energy.get("hasHeatPump"),
            "has_photovoltaic_panels": energy.get("hasPhotovoltaicPanels"),
            "has_thermic_panels": energy.get("hasThermicPanels"),
            "has_collective_water_heater": energy.get("hasCollectiveWaterHeater"),
            # --- certificates ---
            "epc_score": certs.get("epcScore"),
            "epc_reference": certs.get("epcReference"),
            "epc_url": certs.get("epcUrl"),
            "epc_description": certs.get("epcDescription"),
            "epc_consumption_yearly": certs.get("primaryEnergyConsumptionYearly"),
            "carbon_emission": certs.get("carbonEmission"),
            "renovation_obligation": certs.get("renovationObligation"),
            "primary_energy_consumption_level": pcerts.get("primaryEnergyConsumptionLevel"),
            "global_insulation_level": pcerts.get("globalInsulationLevel"),
            "has_asbestos_certificate": pcerts.get("hasAsbestosCertificate"),
            "has_electrical_compliance_certificate": pcerts.get(
                "hasElectricalInstallationComplianceCertificate"
            ),
            "oil_tank_certificate_status": pcerts.get("oilTankCertificateStatus"),
            "has_valid_flood_certificate": pcerts.get("hasValidFloodCertificate"),
            "has_judicial_measure": pcerts.get("hasJudicialMeasure"),
            "has_separate_water_meter": pcerts.get("hasSeparateWaterMeter"),
            "has_separate_gas_meter": pcerts.get("hasSeparateGasMeter"),
            "has_separate_electricity_meter": pcerts.get("hasSeparateElectricityMeter"),
            "built_plan_status": pcerts.get("builtPlanStatus"),
            "enforcement_measures_register_consulted": pcerts.get(
                "enforcementMeasuresRegisterConsulted"
            ),
            # --- construction permit / planning ---
            "permit_construction_type": permit.get("constructionType"),
            "permit_is_obtained": permit.get("isObtained"),
            "urban_development_zoning": permit.get("mostRecentUrbanDevelopmentZoning"),
            "urban_planning_information": permit.get("urbanPlanningInformation"),
            "is_breaching_urban_planning_regulation": permit.get(
                "isBreachingUrbanPlanningRegulation"
            ),
            "has_plot_division_authorization": permit.get("hasPlotDivisionAuthorization"),
            "has_priority_purchase_right": permit.get("hasPossiblePriorityPurchaseRight"),
            "has_first_refusal_right": permit.get("hasFirstRefusalRight"),
            "has_obligation_to_construct": permit.get("hasObligationToConstruct"),
            "has_cadastral_plan": permit.get("hasCadastralPlan"),
            "total_buildable_ground_floor_surface": permit.get(
                "totalBuildableGroundFloorSurface"
            ),
            "flood_zone_icon_url": permit.get("floodZoneIconUrl"),
            "g_score": permit.get("gScore"),
            "p_score": permit.get("pScore"),
            # --- commercial specificities ---
            "ceiling_height": spec.get("ceilingHeight"),
            "max_available_height": spec.get("maxAvailableHeight"),
            "min_available_height": spec.get("minAvailableHeight"),
            "total_floor_surface": spec.get("totalFloorSurface"),
            "showroom_surface": spec.get("showroomSurface"),
            "shop_window_width": spec.get("shopWindowWidth"),
            "access_door_count": spec.get("accessDoorCount"),
            "sectional_door_count": spec.get("sectionalDoorCount"),
            "sliding_door_count": spec.get("slidingDoorCount"),
            "covered_bays_count": spec.get("coveredBaysCount"),
            "loading_bay_count": spec.get("loadingBayCount"),
            "loading_bay_with_lifting_device_count": spec.get(
                "loadingBayWithLiftingDeviceCount"
            ),
            "has_goodwill": spec.get("hasGoodwill"),
            "goodwill_price": spec.get("goodwillPrice"),
            "has_reception_desk": spec.get("hasReceptionDesk"),
            "has_workspace": spec.get("hasWorkspace"),
            "internal_fixtures_and_fittings": spec.get("internalFixturesAndFittings"),
            "miscellaneous_fixtures_and_fittings": spec.get(
                "miscellaneousFixturesAndFittings"
            ),
            # --- transaction / financial ---
            "is_subject_to_vat": sale.get("isSubjectToVat"),
            "is_furnished": sale.get("isFurnished"),
            "has_starting_price": sale.get("hasStartingPrice"),
            "home_to_build": sale.get("homeToBuild"),
            "life_annuity": sale.get("lifeAnnuity"),
            "public_sale": sale.get("publicSale"),
            "new_builds_land_price": sale.get("newBuildsLandPrice"),
            "new_builds_land_taxes": sale.get("newBuildsLandTaxes"),
            "new_builds_total_price": sale.get("newBuildsTotalPrice"),
            "new_builds_vat": sale.get("newBuildsVAT"),
            "new_builds_vat_percentage": sale.get("newBuildsVATPercentage"),
            "rental_monthly_price": rental.get("monthlyRentalPrice"),
            "rental_monthly_costs": rental.get("monthlyRentalCosts"),
            "rental_is_furnished": rental.get("isFurnished"),
            "availability_date": txn.get("availabilityDate"),
            "availability_period_type": txn.get("availabilityPeriodType"),
            # --- investor ---
            "is_investment_property": investor.get("isInvestmentProperty"),
            "current_monthly_rental_income": investor.get("currentMonthlyRentalIncome"),
            "expected_monthly_rental_income": investor.get("expectedMonthlyRentalIncome"),
            "current_return_on_investment": investor.get("currentReturnOnInvestment"),
            "expected_return_on_investment": investor.get("expectedReturnOnInvestment"),
            "occupancy_rate": investor.get("occupancyRate"),
            "investor_habitable_unit_count": investor.get("habitableUnitCount"),
            # --- flags ---
            "is_newly_built": flags.get("isNewlyBuilt"),
            "is_new_classified": flags.get("isNewClassified"),
            "is_new_price": flags.get("isNewPrice"),
            "is_sold_or_rented": flags.get("isSoldOrRented"),
            "is_under_option": flags.get("isUnderOption"),
            "is_public_sale": flags.get("isPublicSale"),
            "is_notary_sale": flags.get("isNotarySale"),
            "is_life_annuity_sale": flags.get("isLifeAnnuitySale"),
            "is_investment_project": flags.get("isInvestmentProject"),
            "is_interactive_sale": flags.get("isAnInteractiveSale"),
            "is_new_real_estate_project": flags.get("isNewRealEstateProject"),
            "is_low_energy": flags.get("isLowEnergy"),
            "is_passive_house": flags.get("isPassiveHouse"),
            "percent_sold": flags.get("percentSold"),
            # --- publication / statistics ---
            "visualisation_option": pub.get("visualisationOption"),
            "detailed_page_visibility": pub.get("detailedPageVisibility"),
            "publisher_id": pub.get("publisherId"),
            "view_count": stats.get("viewCount"),
            "bookmark_count": stats.get("bookmarkCount"),
            # --- media counts ---
            "picture_count": len(self._pictures),
            "document_count": len(self._documents),
            "virtual_tour_url": _g(self.classified, "media", "virtualTourUrl"),
            "external_video_url": _g(self.classified, "media", "externalVideoUrl"),
            "virtual_experience_url": _g(self.classified, "media", "virtualExperienceUrl"),
            "external_video_embed_url": _g(self.classified, "media", "externalVideoEmbedUrl"),
            "external_video_thumbnail_url": _g(
                self.classified, "media", "externalVideoThumbnailUrl"
            ),
            # --- land ---
            "land_sewer_connection": _g(prop, "land", "sewerConnection"),
            "land_latest_use_designation": _g(prop, "land", "latestUseDesignation"),
            "land_width": _g(prop, "land", "landWidth"),
            "workspace_surface": _g(spec, "workspace", "surface"),
            "office_surface": _g(spec, "office", "surface"),
            "floor_plans": _g(self.classified, "media", "floorPlans"),
            "specifications": _g(self.classified, "media", "specifications"),
            "legal_documents": _g(self.classified, "media", "legalDocuments"),
            # --- display flags ---
            "display_flag_main": _g(self.classified, "displayFlags", "main"),
            "display_flag_secondary": _g(self.classified, "displayFlags", "secondary"),
            # Which detail sections immoweb renders for this listing; a useful
            # signal for how complete the agent's own submission was.
            "has_sections": self.classified.get("hasSectionsArray") or {},
        }

    @field
    def raw(self) -> Optional[Dict[str, Any]]:
        return self.classified or None
