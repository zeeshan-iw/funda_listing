from typing import Any, Dict, List, Optional

import attrs


@attrs.define(kw_only=True)
class Agent:
    id: Optional[str] = ""
    office_id: Optional[str] = ""
    name: Optional[str] = ""
    association: Optional[str] = ""
    relative_url: Optional[str] = ""
    logo_id: Optional[str] = ""
    logo_url: Optional[str] = ""
    is_primary: bool = False


@attrs.define(kw_only=True)
class Address:
    country: Optional[str] = ""
    province: Optional[str] = ""
    city: Optional[str] = ""
    municipality: Optional[str] = ""
    street_name: Optional[str] = ""
    house_number: Optional[str] = ""
    house_number_suffix: Optional[str] = ""   # Requirement #3
    postal_code: Optional[str] = ""
    wijk: Optional[str] = ""
    neighbourhood: Optional[str] = ""
    identifiers: List[str] = attrs.field(factory=list)
    is_bag_address: bool = True


@attrs.define(kw_only=True)
class RangeValue:
    gte: Optional[int] = None
    lte: Optional[int] = None


@attrs.define(kw_only=True)
class PriceInfo:
    selling_price: List[int] = attrs.field(factory=list)
    selling_price_range: Optional[RangeValue] = None
    selling_price_type: Optional[str] = ""
    selling_price_condition: Optional[str] = ""
    rent_price: List[int] = attrs.field(factory=list)
    rent_price_range: Optional[RangeValue] = None
    rent_price_type: Optional[str] = ""
    rent_price_condition: Optional[str] = ""


@attrs.define(kw_only=True)
class FundaListingItem:
    # Basic Info
    id: Optional[int] = None
    status: Optional[str] = ""              # Requirement #5 — mapped to English granular value
    listing_category: Optional[str] = ""   # Requirement #2 — buy / rent / new
    publish_date: Optional[str] = ""
    object_detail_page_relative_url: Optional[str] = ""
    object_type: Optional[str] = ""
    offering_type: Optional[str] = ""
    construction_type: Optional[str] = ""
    zoning: Optional[str] = ""

    build: Dict[str, Any] = attrs.field(factory=dict)
    amenities: List[str] = attrs.field(factory=list)
    outdoor_space: Dict[str, Any] = attrs.field(factory=dict)
    garden_location: Dict[str, Any] = attrs.field(factory=dict)
    storage_space: Dict[str, Any] = attrs.field(factory=dict)
    garage: Dict[str, Any] = attrs.field(factory=dict)
    parking: Dict[str, Any] = attrs.field(factory=dict)
    feature: Dict[str, Any] = attrs.field(factory=dict)

    full_description: Optional[str] = ""
    thumbnail_id: List[str] = attrs.field(factory=list)
    image_urls: List[str] = attrs.field(factory=list)       # Requirement #1
    available_media_types: List[str] = attrs.field(factory=list)
    product_entitlement: List[str] = attrs.field(factory=list)
    blikvanger: Dict[str, Any] = attrs.field(factory=dict)

    # Nested Objects
    address: Optional[Address] = None
    agents: List[Agent] = attrs.field(factory=list)
    price: Optional[PriceInfo] = None

    number_of_rooms: Optional[int] = None
    number_of_bedrooms: Optional[int] = None
    energy_label: Optional[str] = ""
    floor_area: List[int] = attrs.field(factory=list)
    floor_area_range: Optional[RangeValue] = None
    plot_area: List[int] = attrs.field(factory=list)
    plot_area_range: Optional[RangeValue] = None