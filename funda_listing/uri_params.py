from datetime import datetime, timezone


def uri_params(params, spider):
    return {**params, "date": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
