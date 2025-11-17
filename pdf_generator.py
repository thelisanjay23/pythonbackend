"""
PDF Invoice Generator for Tumble Time Pvt Ltd
Generates professional PDF invoices
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from io import BytesIO
from datetime import datetime

def generate_pdf_invoice(invoice_data: dict) -> bytes:
    """Generate PDF invoice and return as bytes"""
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)
    
    # Container for PDF elements
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#FF1493'),
        spaceAfter=6,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#000000'),
        spaceAfter=12,
        fontName='Helvetica-Bold'
    )
    
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#000000'),
    )
    
    small_style = ParagraphStyle(
        'CustomSmall',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor('#666666'),
    )
    
    # Company Header
    elements.append(Paragraph(invoice_data['company']['name'].upper(), title_style))
    elements.append(Paragraph(invoice_data['company']['address'], normal_style))
    elements.append(Paragraph(invoice_data['company']['city'], normal_style))
    elements.append(Paragraph(f"Phone: {invoice_data['company']['phone']}", normal_style))
    elements.append(Paragraph(f"Email: {invoice_data['company']['email']}", normal_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Invoice Details Header
    invoice_header_data = [
        ['Invoice Number:', invoice_data['invoice_number'], 'Invoice Date:', invoice_data['invoice_date']],
        ['Status:', invoice_data['status'], 'Payment ID:', invoice_data['payment']['payment_id'][:20]],
    ]
    
    invoice_header_table = Table(invoice_header_data, colWidths=[1.5*inch, 2*inch, 1.5*inch, 2*inch])
    invoice_header_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#666666')),
        ('TEXTCOLOR', (2, 0), (2, -1), colors.HexColor('#666666')),
        ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#00FF88')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
    ]))
    
    elements.append(invoice_header_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Bill To Section
    elements.append(Paragraph("BILL TO:", heading_style))
    elements.append(Paragraph(invoice_data['customer']['name'], normal_style))
    elements.append(Paragraph(invoice_data['customer']['phone'], normal_style))
    elements.append(Paragraph(invoice_data['customer']['email'], normal_style))
    elements.append(Paragraph(invoice_data['customer']['address'], normal_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Enrollment Details
    elements.append(Paragraph("ENROLLMENT DETAILS:", heading_style))
    enrollment_data = [
        ['Child Name:', invoice_data['enrollment']['child_name']],
        ['Program:', invoice_data['enrollment']['program_name']],
        ['Center:', invoice_data['enrollment']['center_name']],
        ['Duration:', f"{invoice_data['enrollment']['duration_months']} Months"],
        ['Start Date:', invoice_data['enrollment']['start_date']],
        ['End Date:', invoice_data['enrollment']['end_date']],
        ['Frequency:', f"{invoice_data['enrollment']['classes_per_week']} days/week"],
        ['Total Classes:', str(invoice_data['enrollment']['total_classes'])],
    ]
    
    enrollment_table = Table(enrollment_data, colWidths=[2*inch, 4.5*inch])
    enrollment_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#666666')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    
    elements.append(enrollment_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Financial Breakdown
    elements.append(Paragraph("PAYMENT BREAKDOWN:", heading_style))
    financial_data = [
        ['Description', 'Amount'],
        ['Base Amount', f"₹{invoice_data['financial']['base_amount']:,.2f}"],
        [f"CGST ({invoice_data['financial']['cgst_rate']}%)", f"₹{invoice_data['financial']['cgst_amount']:,.2f}"],
        [f"SGST ({invoice_data['financial']['sgst_rate']}%)", f"₹{invoice_data['financial']['sgst_amount']:,.2f}"],
        ['', ''],
        ['TOTAL AMOUNT', f"₹{invoice_data['financial']['total_amount']:,.2f}"],
    ]
    
    financial_table = Table(financial_data, colWidths=[4.5*inch, 2*inch])
    financial_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f0f0')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (-1, -1), 12),
        ('TEXTCOLOR', (0, -1), (-1, -1), colors.HexColor('#FF1493')),
        ('LINEABOVE', (0, -1), (-1, -1), 2, colors.black),
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.grey),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    
    elements.append(financial_table)
    elements.append(Paragraph(f"<i>Amount in Words: {invoice_data['financial']['amount_in_words']}</i>", small_style))
    elements.append(Spacer(1, 0.3*inch))
    
    # Terms & Conditions
    elements.append(Paragraph("TERMS & CONDITIONS:", heading_style))
    for i, term in enumerate(invoice_data['terms_and_conditions'][:5], 1):  # First 5 terms
        elements.append(Paragraph(f"{i}. {term}", small_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Footer
    footer_data = [
        [f"GSTIN: {invoice_data['company']['gstin']}", f"PAN: {invoice_data['company']['pan']}"],
    ]
    
    footer_table = Table(footer_data, colWidths=[3.25*inch, 3.25*inch])
    footer_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#666666')),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
    ]))
    
    elements.append(footer_table)
    elements.append(Spacer(1, 0.1*inch))
    elements.append(Paragraph("<i>This is a computer-generated invoice and does not require a signature.</i>", small_style))
    elements.append(Paragraph("<b>Thank you for choosing Tumble Gym!</b>", normal_style))
    
    # Build PDF
    doc.build(elements)
    
    # Get PDF bytes
    pdf_bytes = buffer.getvalue()
    buffer.close()
    
    return pdf_bytes
