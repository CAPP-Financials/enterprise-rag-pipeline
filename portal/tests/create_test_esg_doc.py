"""
Create a realistic sample ESG report as a plain text file for end-to-end portal testing.
We'll use a .txt file since the portal supports text and it avoids PDF binary complexity.
"""
from fpdf import FPDF

content = """
GREENTECH SOLUTIONS PLC
Sustainability Report 2024

EXECUTIVE SUMMARY

GreenTech Solutions is committed to achieving net-zero carbon emissions by 2035 across all Scope 1 and Scope 2 operations.
In 2024, we reduced our total greenhouse gas emissions by 42% compared to our 2019 baseline, verified by Bureau Veritas under ISO 14064.
Our renewable energy consumption reached 3.2 GW of installed capacity across 14 countries, representing 78% of our total electricity demand.

CLIMATE & EMISSIONS

We have set a science-based target aligned with the Paris Agreement 1.5°C pathway, approved by the Science Based Targets initiative (SBTi) in March 2024.
Total Scope 1 and Scope 2 emissions in 2024 were 1.2 million tonnes CO2 equivalent, down from 2.07 million tonnes in 2019.
Scope 3 emissions from our supply chain were independently assessed at 8.4 million tonnes CO2e, with a 15% reduction target by 2027.
We invested EUR 340 million in low-carbon technologies and energy efficiency programmes during 2024.
Our carbon intensity per unit of revenue improved by 31% year-on-year, from 42 tCO2e per EUR million to 29 tCO2e per EUR million.

ENERGY

Total energy consumption in 2024 was 18.7 TWh, a reduction of 12% from 21.3 TWh in 2023.
We procured 14.6 TWh of renewable electricity through Power Purchase Agreements (PPAs) and on-site generation.
Energy intensity improved to 0.43 MWh per unit of production, compared to 0.51 MWh in 2022.
We installed 450 MW of rooftop solar capacity across our manufacturing facilities in India, Germany, and Brazil.
Our energy efficiency programme delivered EUR 28 million in cost savings and avoided 180,000 tonnes of CO2 emissions in 2024.

WATER

Total water withdrawal in 2024 was 4.2 million cubic metres, a 19% reduction from 5.2 million cubic metres in 2023.
We achieved a water recycling rate of 73% across our manufacturing operations, up from 61% in 2022.
Zero liquid discharge systems were implemented at 8 of our 12 high water-stress facilities.
Our water intensity ratio improved to 0.8 cubic metres per tonne of output, against a 2025 target of 0.75 cubic metres per tonne.

BIODIVERSITY

We committed to a net positive biodiversity impact by 2030, aligned with the Taskforce on Nature-related Financial Disclosures (TNFD) framework.
In 2024, we restored 1,200 hectares of degraded land adjacent to our operations in Brazil and Indonesia.
Zero deforestation commitment covers 100% of our agricultural commodity supply chains, verified by satellite monitoring.

SOCIAL & LABOUR

Total workforce in 2024 was 47,500 employees across 32 countries, with a voluntary turnover rate of 8.2%.
Women represent 38% of our total workforce and 29% of senior management positions, up from 24% in 2021.
We achieved a gender pay gap of 3.2% (median), down from 7.8% in 2020, with a target of full pay parity by 2026.
Lost Time Injury Rate (LTIR) improved to 0.18 per 200,000 hours worked, a 34% improvement from 0.27 in 2022.
We invested EUR 42 million in employee training and development, averaging 48 hours of training per employee per year.
Our supply chain due diligence programme covered 94% of Tier 1 suppliers by spend, with 100% of high-risk suppliers audited.

CIRCULAR ECONOMY & WASTE

Total waste generated in 2024 was 82,000 tonnes, with a recycling and recovery rate of 91%.
We diverted 74,600 tonnes of waste from landfill through recycling, composting, and energy recovery.
Our packaging reduction programme eliminated 8,400 tonnes of single-use plastic from our product lines.
We launched a product take-back scheme in 18 markets, recovering 12,000 tonnes of end-of-life products for refurbishment or recycling.

GOVERNANCE

Our Board of Directors includes 11 members, of whom 45% are women and 36% are from underrepresented ethnic groups.
ESG performance metrics are directly linked to executive compensation, representing 25% of the annual bonus for the CEO and CFO.
We report in accordance with GRI Standards (Core option), TCFD recommendations, and the EU Corporate Sustainability Reporting Directive (CSRD).
Our anti-corruption training programme achieved 99.7% completion across all employees in positions of financial authority.
We received no material regulatory fines or sanctions related to environmental, social, or governance matters in 2024.

FORWARD-LOOKING TARGETS

By 2030, we target a 70% absolute reduction in Scope 1 and 2 emissions against our 2019 baseline.
We are committed to sourcing 100% renewable electricity by 2027 across all wholly-owned operations.
Our science-based Scope 3 target requires a 30% reduction in supply chain emissions intensity by 2030.
We will achieve zero waste to landfill across all manufacturing sites by 2026.

This report has been prepared in accordance with the GRI Sustainability Reporting Standards 2021 and has been externally assured by Deloitte to a limited assurance level.
"""

# Create PDF
pdf = FPDF()
pdf.add_page()
pdf.set_font("Helvetica", "B", 16)
pdf.cell(0, 10, "GreenTech Solutions PLC - Sustainability Report 2024", ln=True, align="C")
pdf.ln(5)

pdf.set_font("Helvetica", size=10)
for line in content.strip().split("\n"):
    line = line.strip()
    if not line:
        pdf.ln(3)
    elif line.isupper() and len(line) < 60:
        pdf.set_font("Helvetica", "B", 11)
        pdf.ln(2)
        pdf.cell(0, 7, line, ln=True)
        pdf.set_font("Helvetica", size=10)
    else:
        pdf.multi_cell(0, 5, line)

pdf.output("/home/ubuntu/greentech_esg_report_2024.pdf")
print(f"PDF created: /home/ubuntu/greentech_esg_report_2024.pdf")

# Also create a plain text version
with open("/home/ubuntu/greentech_esg_report_2024.txt", "w") as f:
    f.write(content)
print(f"TXT created: /home/ubuntu/greentech_esg_report_2024.txt")

# Count expected ESG sentences
import re
sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9])', content)
sentences = [s.strip() for s in sentences if len(s.strip()) > 40]
print(f"Total sentences: {len(sentences)}")

esg_keywords = re.compile(
    r'\b(carbon|co2|ghg|greenhouse|emission|net.zero|scope [123]|climate|renewable|energy|water|waste|'
    r'biodiversity|employee|worker|diversity|gender|safety|supply chain|governance|board|gri|tcfd|csrd|'
    r'circular|recycl|landfill|deforestation|science.based|target|reduction|intensity)\b',
    re.IGNORECASE
)
esg_sentences = [s for s in sentences if esg_keywords.search(s) and len(s) > 40 and len(s) < 800]
print(f"Expected ESG claims: {len(esg_sentences)}")
for i, s in enumerate(esg_sentences[:5]):
    print(f"  [{i+1}] {s[:80]}...")
