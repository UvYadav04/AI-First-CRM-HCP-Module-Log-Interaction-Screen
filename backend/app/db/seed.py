"""Seed a handful of fake HCPs and materials so search_hcp / search_material
have something to actually query. Run with: python -m app.db.seed"""
from app.db.database import SessionLocal, init_db
from app.db.models import HCP, Material

HCPS = [
    {"name": "Dr. Priya Sharma", "specialty": "Oncology", "affiliation": "City Hospital"},
    {"name": "Dr. Raj Malhotra", "specialty": "Cardiology", "affiliation": "Apollo Clinic"},
    {"name": "Dr. Emily Smith", "specialty": "Oncology", "affiliation": "St. Mary's Medical Center"},
    {"name": "Dr. John Smith", "specialty": "Cardiology", "affiliation": "Metro Heart Institute"},
    {"name": "Dr. Ananya Iyer", "specialty": "Endocrinology", "affiliation": "Fortis Hospital"},
    {"name": "Dr. Vikram Rao", "specialty": "Neurology", "affiliation": "Manipal Hospital"},
    {"name": "Dr. Sarah Chen", "specialty": "Dermatology", "affiliation": "Sunrise Clinic"},
    {"name": "Dr. Arjun Nair", "specialty": "Pulmonology", "affiliation": "AIIMS"},
    {"name": "Dr. Meera Kapoor", "specialty": "Gynecology", "affiliation": "Cloudnine Hospital"},
    {"name": "Dr. David Wilson", "specialty": "Oncology", "affiliation": "Memorial Cancer Center"},
    {"name": "Dr. Kavita Deshmukh", "specialty": "Rheumatology", "affiliation": "Ruby Hall Clinic"},
    {"name": "Dr. Aditya Verma", "specialty": "Cardiology", "affiliation": "Max Healthcare"},
]

MATERIALS = [
    {"title": "Prodo-X Efficacy Brochure", "type": "brochure", "product_name": "Prodo-X", "approved": True},
    {"title": "Prodo-X Prescribing Information", "type": "PI", "product_name": "Prodo-X", "approved": True},
    {"title": "OncoBoost Phase III Study Reprint", "type": "reprint", "product_name": "OncoBoost", "approved": True},
    {"title": "OncoBoost Patient Leave-Behind", "type": "leave-behind", "product_name": "OncoBoost", "approved": True},
    {"title": "CardioShield Safety Data Sheet", "type": "reprint", "product_name": "CardioShield", "approved": True},
    {"title": "CardioShield Dosage Guide", "type": "brochure", "product_name": "CardioShield", "approved": True},
    {"title": "NeuroCalm Mechanism of Action Deck", "type": "brochure", "product_name": "NeuroCalm", "approved": True},
]


def seed() -> None:
    init_db()
    db = SessionLocal()
    try:
        if not db.query(HCP).first():
            db.bulk_insert_mappings(HCP, HCPS)
        if not db.query(Material).first():
            db.bulk_insert_mappings(Material, MATERIALS)
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
    print("Seeded hcps + materials.")
