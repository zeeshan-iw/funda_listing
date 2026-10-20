import base64
import os
import tempfile


class GCSCredentials:
    @classmethod
    def from_crawler(cls, crawler):
        b64 = crawler.settings.get("GCP_SA_KEY_B64")
        if b64:
            b64 = b64.strip()
            b64 += "=" * (-len(b64) % 4)
            p = os.path.join(tempfile.gettempdir(), "gcp_sa.json")
            with open(p, "wb") as f:
                f.write(base64.b64decode(b64))
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = p
        # The Dash Spider Settings name the project FUNDA_GCS_PROJECT_ID;
        # map it onto the setting Scrapy's GCS feed storage actually reads.
        # This extension runs before feeds open, so the override lands in time.
        project = crawler.settings.get("FUNDA_GCS_PROJECT_ID")
        if project:
            crawler.settings.set("GCS_PROJECT_ID", project, priority="cmdline")
        return cls()
