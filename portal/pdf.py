from io import BytesIO
from xml.sax.saxutils import escape
from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image

def document(title, subtitle, sections, rows=None, headers=None):
    output=BytesIO()
    doc=SimpleDocTemplate(output,pagesize=(210*mm,297*mm),rightMargin=18*mm,leftMargin=18*mm,topMargin=18*mm,bottomMargin=20*mm)
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Body',fontName='Helvetica',fontSize=10,leading=15,spaceAfter=8,textColor=colors.HexColor('#293d51')))
    styles['Title'].textColor=colors.HexColor('#173e62')
    def para(text,style='Body'):
        return Paragraph(escape(str(text)).replace('\n','<br/>'),styles[style])
    story=[]
    logo=settings.BASE_DIR/'static/brand/logo.png'
    if logo.exists(): story.extend([Image(str(logo),width=22*mm,height=20*mm,kind='proportional',hAlign='LEFT'),Spacer(1,8)])
    story.extend([para(title,'Title'),para(subtitle),Spacer(1,10)])
    for heading,content in sections:
        story.extend([para(heading,'Heading2'),para(content)])
    if rows is not None:
        table_rows=[[para(v) for v in row] for row in ([headers]+rows if headers else rows)]
        if table_rows:
            table=Table(table_rows,colWidths=[doc.width/len(table_rows[0])]*len(table_rows[0]),repeatRows=1 if headers else 0,hAlign='LEFT')
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf2f8')),('VALIGN',(0,0),(-1,-1),'TOP'),
                ('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor('#d7e1e9')),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7)]))
            story.append(table)
    def footer(canvas, document):
        canvas.setFont('Helvetica',8);canvas.setFillColor(colors.HexColor('#63768a'))
        canvas.drawString(18*mm,12*mm,'HelloSama | Sama Tours | info@hellosama.com')
        canvas.drawRightString(192*mm,12*mm,f'Page {document.page}')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    output.seek(0)
    return output

def quote_pdf(quote):
    req=quote.request
    return document('QUOTATION',f'{quote.reference} | {req.company.name}',[
        ('Your trip',f'{req.title}\n{req.origin} to {req.destination}\nDeparture: {req.departure} | Travellers: {req.travellers}'),
        ('Total',f'{quote.amount:,.2f} {quote.currency}'),('Travel details',quote.details),
        ('Included',quote.inclusions or 'As described above'),('Not included',quote.exclusions or 'Please confirm with your Sama representative.'),
        ('Payment terms',quote.payment_terms),('Validity',quote.valid_until.strftime('%d %b %Y, %H:%M %Z')),
        ('Approval and booking','Submit this quotation for approval in HelloSama. Every designated approver must approve the same version. Approval does not confirm a booking; Sama will verify availability and confirm separately.'),
        ('Version status','Superseded - do not use for booking.' if quote.superseded else 'This document reflects the quotation version shown above. Check the portal for its latest approval and booking status.')])
