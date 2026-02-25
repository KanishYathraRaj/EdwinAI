from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER
from io import BytesIO


def question_bank_to_pdf(data):
    """Generate PDF in memory and return a BytesIO object."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()

    # Define styles
    title_style = ParagraphStyle(
        'CourseTitle',
        parent=styles['Heading1'],
        fontSize=20,
        alignment=TA_CENTER,
        textColor="#1A5276",
        spaceAfter=20
    )
    unit_title_style = ParagraphStyle(
        'UnitTitle',
        parent=styles['Heading2'],
        fontSize=16,
        textColor="#2471A3",
        spaceAfter=10
    )
    qtype_style = ParagraphStyle(
        'QType',
        parent=styles['Heading3'],
        fontSize=14,
        textColor="#424949",
        spaceAfter=6
    )
    question_style = ParagraphStyle(
        'Question',
        parent=styles['Normal'],
        fontSize=11,
        leading=18,
        textColor="#2C3E50",
        spaceAfter=8
    )

    elements = []
    elements.append(Paragraph(data.get("course_title", "Question Bank"), title_style))
    elements.append(Spacer(1, 12))

    # Add Question Bank
    if "questions" in data:
        q_data = data["questions"]
        if "2_marks" in q_data and q_data["2_marks"]:
            elements.append(Paragraph("📘 2 MARK QUESTIONS", qtype_style))
            for i, q in enumerate(q_data["2_marks"], 1):
                elements.append(Paragraph(f"{i}. {q}", question_style))
            elements.append(Spacer(1, 12))

        if "16_marks" in q_data and q_data["16_marks"]:
            elements.append(Paragraph("🧠 16 MARK QUESTIONS", qtype_style))
            for i, q in enumerate(q_data["16_marks"], 1):
                elements.append(Paragraph(f"{i}. {q}", question_style))
            elements.append(PageBreak())

    # Add Answer Key
    if "answer_key" in data:
        elements.append(Paragraph("🔑 ANSWER KEY", title_style))
        elements.append(Spacer(1, 12))
        ak_data = data["answer_key"]
        if "2_marks" in ak_data and ak_data["2_marks"]:
            elements.append(Paragraph("📘 2 MARK ANSWERS", qtype_style))
            for i, ans in enumerate(ak_data["2_marks"], 1):
                elements.append(Paragraph(f"<b>Question {i}</b>", question_style))
                elements.append(Paragraph(ans.get("answer", ""), question_style))
                elements.append(Paragraph(f"<i>Reference: {ans.get('references', '')}</i>", ParagraphStyle('Ref', parent=question_style, fontSize=9, textColor="#7F8C8D")))
                elements.append(Spacer(1, 6))
            elements.append(Spacer(1, 12))

        if "16_marks" in ak_data and ak_data["16_marks"]:
            elements.append(Paragraph("🧠 16 MARK ANSWERS", qtype_style))
            for i, ans in enumerate(ak_data["16_marks"], 1):
                elements.append(Paragraph(f"<b>Question {i}</b>", question_style))
                elements.append(Paragraph(ans.get("answer", ""), question_style))
                elements.append(Paragraph(f"<i>Reference: {ans.get('references', '')}</i>", ParagraphStyle('Ref', parent=question_style, fontSize=9, textColor="#7F8C8D")))
                elements.append(Spacer(1, 6))
            elements.append(PageBreak())

    doc.build(elements)
    buffer.seek(0)
    return buffer