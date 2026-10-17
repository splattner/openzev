import csv
import io

from rest_framework.renderers import BaseRenderer

from .dataset import COLUMNS


class SeriesCsvRenderer(BaseRenderer):
    """``?format=csv`` (or ``Accept: text/csv``): the series as one header row plus one row per record.

    An error response has no ``results``; it is rendered as a single ``detail``
    line, so a failing spreadsheet refresh shows why instead of a blank sheet.
    """

    media_type = "text/csv"
    format = "csv"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if data is None:
            return b""
        out = io.StringIO()
        if isinstance(data, dict) and "results" in data:
            writer = csv.writer(out, lineterminator="\n")
            writer.writerow(COLUMNS)
            for row in data["results"]:
                writer.writerow(["" if row[column] is None else row[column] for column in COLUMNS])
        else:
            detail = data.get("detail") if isinstance(data, dict) else data
            out.write(f"{detail}\n")
        return out.getvalue().encode(self.charset)
