from typing import Any, Dict, List, Optional

import attrs


@attrs.define(kw_only=True)
class Agent:
    id: Optional[str] = ""
    name: Optional[str] = ""
    office_id: Optional[str] = ""
    association: Optional[str] = ""
    relative_url: Optional[str] = ""
    logo_url: Optional[str] = ""
    is_primary: bool = False
    # -- added: immoweb exposes full contact + office address per customer,
    # all of which used to be dropped on the floor.
    email: Optional[str] = ""
    phone: Optional[str] = ""
    mobile: Optional[str] = ""
    ipi_number: Optional[str] = ""
    year_of_foundation: Optional[int] = None
    office_street: Optional[str] = ""
    office_postal_code: Optional[str] = ""
    office_city: Optional[str] = ""
    office_country: Optional[str] = ""
    office_province: Optional[str] = ""
    office_district: Optional[str] = ""
    office_latitude: Optional[float] = None
    office_longitude: Optional[float] = None
    contact_hours_landline: Optional[Any] = None
    contact_hours_mobile: Optional[Any] = None
    sales_rep_name: Optional[str] = ""
    sales_rep_email: Optional[str] = ""
    sales_rep_phone: Optional[str] = ""
    # Developer/project counters on the customer record. Null on most
    # listings; surfaced by the include_raw mapping check on 2026-08-21.
    number_of_active_projects: Optional[int] = None
    number_of_projects_sold: Optional[int] = None
    features: Dict[str, Any] = attrs.field(factory=dict)


@attrs.define(kw_only=True)
class Address:
    country: Optional[str] = ""
    province: Optional[str] = ""
    city: Optional[str] = ""
    municipality: Optional[str] = ""
    street_name: Optional[str] = ""
    house_number: Optional[str] = ""
    house_number_suffix: Optional[str] = ""
    postal_code: Optional[str] = ""
    neighbourhood: Optional[str] = ""
    wijk: Optional[str] = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # -- added
    region_code: Optional[str] = ""
    floor: Optional[int] = None
    has_sea_view: Optional[bool] = None
    is_approximated: Optional[bool] = None
    property_name: Optional[str] = ""
    location_type: Optional[str] = ""


@attrs.define(kw_only=True)
class RangeValue:
    gte: Optional[int] = None
    lte: Optional[int] = None


@attrs.define(kw_only=True)
class PriceInfo:
    selling_price: List[int] = attrs.field(factory=list)
    selling_price_type: Optional[str] = ""
    selling_price_condition: Optional[str] = ""
    rent_price: List[int] = attrs.field(factory=list)
    rent_price_type: Optional[str] = ""
    display_price: Optional[str] = ""
    # -- added
    currency: Optional[str] = "EUR"
    main_value: Optional[int] = None
    old_value: Optional[int] = None
    old_display_price: Optional[str] = ""
    price_per_sqm: Optional[int] = None
    min_range_value: Optional[int] = None
    max_range_value: Optional[int] = None
    is_price_hidden: Optional[bool] = None
    has_starting_price: Optional[bool] = None
    monthly_costs: Optional[int] = None
    cadastral_income: Optional[int] = None
    transaction_subtype: Optional[str] = ""
    price_label: Optional[str] = ""
    price_type: Optional[str] = ""
    html_display_price: Optional[str] = ""
    short_display_price: Optional[str] = ""
    accessibility_price: Optional[str] = ""
    alternative_display_price: Optional[str] = ""
    language: Optional[str] = ""


@attrs.define(kw_only=True)
class Document:
    id: Optional[str] = ""
    type: Optional[str] = ""
    url: Optional[str] = ""
    original_name: Optional[str] = ""
    hash: Optional[str] = ""


@attrs.define(kw_only=True)
class Image:
    small_url: Optional[str] = ""
    medium_url: Optional[str] = ""
    large_url: Optional[str] = ""
    extralarge_url: Optional[str] = ""
    is_vertical: Optional[bool] = None


@attrs.define(kw_only=True)
class ImmowebListingItem:
    id: Optional[int] = None
    # -- added: the client could not verify a single row without these.
    url: Optional[str] = ""
    scraped_at: Optional[str] = ""

    status: Optional[str] = ""
    listing_category: Optional[str] = ""
    publish_date: Optional[str] = ""
    object_type: Optional[str] = ""
    offering_type: Optional[str] = ""
    construction_type: Optional[str] = ""
    zoning: Optional[str] = ""

    full_description: Optional[str] = ""
    image_urls: List[str] = attrs.field(factory=list)
    thumbnail_id: List[str] = attrs.field(factory=list)
    available_media_types: List[str] = attrs.field(factory=list)

    address: Optional[Address] = None
    agents: List[Agent] = attrs.field(factory=list)
    price: Optional[PriceInfo] = None

    number_of_rooms: Optional[int] = None
    number_of_bedrooms: Optional[int] = None
    number_of_bathrooms: Optional[int] = None
    energy_label: Optional[str] = ""
    floor_area: List[int] = attrs.field(factory=list)
    floor_area_range: Optional[RangeValue] = None
    plot_area: List[int] = attrs.field(factory=list)
    plot_area_range: Optional[RangeValue] = None

    feature: Dict[str, Any] = attrs.field(factory=dict)

    # -- added top-level fields -------------------------------------------
    title: Optional[str] = ""
    object_subtype: Optional[str] = ""
    external_reference: Optional[str] = ""
    building_condition: Optional[str] = ""
    last_modified_date: Optional[str] = ""
    expiration_date: Optional[str] = ""
    description_fr: Optional[str] = ""
    description_nl: Optional[str] = ""
    documents: List[Document] = attrs.field(factory=list)
    # `image_urls` keeps only the largest size for backwards compatibility;
    # this carries every resolution immoweb publishes per photo.
    images: List[Image] = attrs.field(factory=list)
    number_of_toilets: Optional[int] = None
    number_of_shower_rooms: Optional[int] = None
    # New-development listings carry a `cluster` block describing the project
    # and its individual units (price/surface/bedroom ranges, per-unit status).
    # Null for ordinary resale listings.
    cluster: Optional[Dict[str, Any]] = None

    # Complete untouched `window.classified` payload. Off by default because
    # it adds ~20 KB/listing; enable with `-a include_raw=1`.
    raw: Optional[Dict[str, Any]] = None
