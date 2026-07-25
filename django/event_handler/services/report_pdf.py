from html import escape
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, TableStyle


MAX_PDF_PAGES = 250
MAX_PDF_BYTES = 8 * 1024 * 1024


class PdfTooLarge(Exception):
    pass


class BoundedPdfBuffer(BytesIO):
    def write(self, value):
        if max(self.getbuffer().nbytes, self.tell() + len(value)) > MAX_PDF_BYTES:
            raise PdfTooLarge
        return super().write(value)


def _text(value, *, unit=""):
    if value is None:
        return "Not measured"
    return escape(f"{value}{unit}")


def _paragraph(value, style):
    return Paragraph(escape(str(value)) if value is not None else "Not measured", style)


def _styles():
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold",
            fontSize=18, leading=22, alignment=TA_CENTER, spaceAfter=12,
        ),
        "heading": ParagraphStyle(
            "ReportHeading", parent=styles["Heading2"], fontName="Helvetica-Bold",
            fontSize=13, leading=16, spaceBefore=10, spaceAfter=6,
        ),
        "subheading": ParagraphStyle(
            "ReportSubheading", parent=styles["Heading3"], fontName="Helvetica-Bold",
            fontSize=10, leading=13, spaceBefore=7, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "ReportBody", parent=styles["BodyText"], fontName="Helvetica",
            fontSize=8, leading=11,
        ),
    }


def _result_table(workout_sets, styles):
    rows = [[
        _paragraph("Set ID", styles["body"]),
        _paragraph("Result", styles["body"]),
        _paragraph("Exercise", styles["body"]),
        _paragraph("Set", styles["body"]),
        _paragraph("Rack", styles["body"]),
        _paragraph("Load", styles["body"]),
        _paragraph("Reps", styles["body"]),
        _paragraph("Average", styles["body"]),
        _paragraph("Peak", styles["body"]),
    ]]
    for workout_set in workout_sets:
        rows.append([
            _paragraph(workout_set.get("id"), styles["body"]),
            _paragraph("False set - excluded" if workout_set.get("is_false_set") else "Completed", styles["body"]),
            _paragraph(workout_set.get("exercise"), styles["body"]),
            _paragraph(workout_set.get("set_number"), styles["body"]),
            _paragraph(workout_set.get("rack_number"), styles["body"]),
            _paragraph(_text(workout_set.get("weight_lbs"), unit=" lbs"), styles["body"]),
            _paragraph(workout_set.get("reps_completed"), styles["body"]),
            _paragraph(_text(workout_set.get("avg_velocity"), unit=" m/s"), styles["body"]),
            _paragraph(_text(workout_set.get("peak_velocity"), unit=" m/s"), styles["body"]),
        ])
        for rep in workout_set.get("reps", []):
            rows.append([
                "",
                "",
                _paragraph(f"Rep {rep.get('rep_number')}", styles["body"]),
                "",
                "",
                "",
                "",
                _paragraph(_text(rep.get("mean_velocity"), unit=" m/s"), styles["body"]),
                _paragraph(_text(rep.get("peak_velocity"), unit=" m/s"), styles["body"]),
            ])
    table = LongTable(
        rows,
        repeatRows=1,
        colWidths=[0.4 * inch, 0.7 * inch, 1.0 * inch, 0.3 * inch, 0.35 * inch, 0.55 * inch, 0.35 * inch, 0.65 * inch, 0.6 * inch],
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8ECEF")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#AAB2B8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _athlete_story(entry, styles):
    athlete = entry.get("athlete", {})
    story = [
        _paragraph(athlete.get("name") or "Athlete unavailable", styles["heading"]),
        _paragraph(
            "Rack participation: " + (", ".join(map(str, entry.get("rack_participation", []))) or "None recorded"),
            styles["body"],
        ),
    ]
    progress = entry.get("final_progress")
    if progress is not None:
        story.append(_paragraph(
            f"Final progress: {progress.get('status') or 'Unknown'}; expected set: {_text(progress.get('expected_set_number'))}",
            styles["body"],
        ))
    prescriptions = entry.get("prescriptions", [])
    if prescriptions:
        story.append(_paragraph("Assigned program and effective targets", styles["subheading"]))
        for prescription in prescriptions:
            workout = prescription.get("workout") or {}
            story.append(_paragraph(
                f"{_text(prescription.get('position'))}. {workout.get('name') or 'Workout unavailable'} "
                f"(item { _text(prescription.get('id')) })",
                styles["body"],
            ))
            for exercise in prescription.get("exercises", []):
                velocity = "Not measured" if exercise.get("velocity_min") is None else (
                    f"{exercise.get('velocity_min')}-{exercise.get('velocity_max')} m/s"
                )
                story.append(_paragraph(
                    f"Exercise {exercise.get('id')}: {exercise.get('position')}. {exercise.get('exercise')} | "
                    f"{_text(exercise.get('sets'))} x {_text(exercise.get('reps'))} | "
                    f"{_text(exercise.get('default_weight_lbs'), unit=' lbs')} | {velocity}",
                    styles["body"],
                ))
    story.append(_paragraph("Persisted set records and reps", styles["subheading"]))
    workout_sets = entry.get("sets", [])
    if workout_sets:
        story.append(_result_table(workout_sets, styles))
    else:
        story.append(_paragraph("No persisted set records.", styles["body"]))
    return story


def render_report_pdf(detail):
    styles = _styles()
    session = detail.get("session", {})
    athletes = detail.get("athletes")
    if athletes is None:
        athletes = [detail["athlete"]]
    story = [
        _paragraph(session.get("label") or "Daily report", styles["title"]),
        _paragraph(
            f"Report {detail.get('id')} | {detail.get('local_date')} | "
            f"{_text(session.get('started_at'))} to {_text(session.get('ended_at'))}",
            styles["body"],
        ),
        Spacer(1, 8),
    ]
    for index, athlete in enumerate(athletes):
        if index:
            story.append(PageBreak())
        story.extend(_athlete_story(athlete, styles))

    output = BoundedPdfBuffer()
    document = SimpleDocTemplate(
        output,
        pagesize=letter,
        rightMargin=0.45 * inch,
        leftMargin=0.45 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.45 * inch,
        title=f"Report {detail.get('id')}",
        author="Edge Athlete",
        creator="Edge Athlete",
        pageCompression=0,
    )

    def enforce_page_limit(_canvas, doc):
        if doc.page > MAX_PDF_PAGES:
            raise PdfTooLarge

    document.build(story, onFirstPage=enforce_page_limit, onLaterPages=enforce_page_limit)
    value = output.getvalue()
    if len(value) > MAX_PDF_BYTES:
        raise PdfTooLarge
    return value
