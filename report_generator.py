import io
from datetime import datetime
from typing import List, Dict, Any, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)


def generate_compliance_pdf_report(
    scan_id: int,
    product_name: str,
    score: int,
    has_violation: bool,
    fields: List[Dict[str, Any]],
    created_at: Optional[datetime] = None,
    user_name: Optional[str] = None,
) -> io.BytesIO:
    """
    Generates a professional Legal Metrology Compliance Audit PDF report
    using ReportLab Platypus, incorporating the SIH26034 hackathon format
    with PackSight branding and itemized rule verification table.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=4,
    )

    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=12,
    )

    section_head_style = ParagraphStyle(
        "SectionHead",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#1e293b"),
        spaceBefore=10,
        spaceAfter=6,
    )

    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#334155"),
    )

    cell_bold_style = ParagraphStyle(
        "CellBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#0f172a"),
    )

    cell_body_style = ParagraphStyle(
        "CellBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#334155"),
    )

    cell_code_style = ParagraphStyle(
        "CellCode",
        parent=styles["Normal"],
        fontName="Courier-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#475569"),
    )

    disclaimer_style = ParagraphStyle(
        "Disclaimer",
        parent=styles["Italic"],
        fontName="Helvetica-Oblique",
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#64748b"),
    )

    elements = []

    # Title and Subtitle
    elements.append(Paragraph("PackSight — Legal Metrology Compliance Report", title_style))
    elements.append(
        Paragraph(
            "Legal Metrology (Packaged Commodities) Rules, 2011 — Automated Audit Certificate",
            subtitle_style,
        )
    )

    # Divider
    elements.append(
        HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#3b82f6"), spaceAfter=12)
    )

    # Status determination
    status_label = "NON-COMPLIANT" if has_violation else "COMPLIANT"
    status_text_color = colors.HexColor("#b91c1c") if has_violation else colors.HexColor("#15803d")

    date_str = created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if created_at else datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # Summary Metadata Box
    summary_data = [
        [
            Paragraph(f"<b>Product Name:</b> {product_name or 'N/A'}", body_style),
            Paragraph(f"<b>Scan ID:</b> #{scan_id}", body_style),
        ],
        [
            Paragraph(f"<b>Auditor / User:</b> {user_name or 'System Auditor'}", body_style),
            Paragraph(f"<b>Audit Date:</b> {date_str}", body_style),
        ],
        [
            Paragraph(f"<b>Overall Score:</b> <b>{score}%</b>", body_style),
            Paragraph(
                f"<b>Status:</b> <font color='{status_text_color.hexval()}'><b>{status_label}</b></font>",
                body_style,
            ),
        ],
    ]

    summary_table = Table(summary_data, colWidths=[270, 270])
    summary_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ])
    )
    elements.append(summary_table)
    elements.append(Spacer(1, 14))

    # Itemized Declarations Section
    elements.append(Paragraph("Itemized LMPC Rule Verification", section_head_style))

    # Table Header
    headers = [
        Paragraph("<b>Rule Code</b>", cell_bold_style),
        Paragraph("<b>Mandatory Declaration</b>", cell_bold_style),
        Paragraph("<b>Status</b>", cell_bold_style),
        Paragraph("<b>Extracted Evidence / Audit Details</b>", cell_bold_style),
    ]

    table_data = [headers]

    for f in fields:
        rule_id = str(f.get("rule_id", "—"))
        field_name = str(f.get("field", "—"))
        verdict = str(f.get("verdict", "review")).upper()
        evidence = str(f.get("evidence", "No text detected"))

        if verdict == "PASS":
            v_color = "#16a34a"
            v_text = f"<font color='{v_color}'><b>PASS</b></font>"
        elif verdict == "FAIL":
            v_color = "#dc2626"
            v_text = f"<font color='{v_color}'><b>VIOLATION</b></font>"
        else:
            v_color = "#d97706"
            v_text = f"<font color='{v_color}'><b>REVIEW</b></font>"

        row = [
            Paragraph(rule_id, cell_code_style),
            Paragraph(f"<b>{field_name}</b>", cell_bold_style),
            Paragraph(v_text, cell_bold_style),
            Paragraph(evidence, cell_body_style),
        ]
        table_data.append(row)

    col_widths = [90, 130, 70, 250]
    rules_table = Table(table_data, colWidths=col_widths, repeatRows=1)

    table_style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
    ]

    for i in range(1, len(table_data)):
        bg = colors.HexColor("#ffffff") if i % 2 != 0 else colors.HexColor("#f8fafc")
        table_style_commands.append(("BACKGROUND", (0, i), (-1, i), bg))

    rules_table.setStyle(TableStyle(table_style_commands))
    elements.append(rules_table)

    elements.append(Spacer(1, 16))

    # Disclaimer from Hackathon project
    disclaimer_text = (
        "<b>Notice & Legal Metrology Disclaimer:</b> This audit report was automatically generated by the "
        "PackSight SIH Legal Metrology Compliance Engine under the Legal Metrology (Packaged Commodities) "
        "Rules, 2011. Results are intended for administrative and preliminary screening purposes. For statutory "
        "enforcement actions, officers must verify flagged items against the physical packaging."
    )
    elements.append(Paragraph(disclaimer_text, disclaimer_style))

    # Build document
    doc.build(elements)
    buffer.seek(0)
    return buffer
