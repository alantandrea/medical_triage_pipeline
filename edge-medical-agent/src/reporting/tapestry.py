"""
Patient Tapestry — color-coded human body visualization.

Generates an inline SVG/HTML snippet that gives clinicians an instant
visual overview of a patient's issues before reading any text.

Color scheme:
    Green   (#4CAF50) — normal / no issues
    Yellow  (#FFEB3B) — caution / borderline
    Orange  (#FF9800) — alert / abnormal
    Red     (#F44336) — emergency / critical

Special icons:
    ✕ red X spanning organ — mass / tumor
    ▲ orange bg            — anatomical finding (fracture, collapse, etc.)
"""
import html
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lab test name → body region mapping
# ---------------------------------------------------------------------------
LAB_TO_REGION: Dict[str, str] = {
    # Liver
    "bilirubin": "liver", "alt": "liver", "ast": "liver", "alp": "liver",
    "ggt": "liver", "albumin": "liver", "total protein": "liver",
    "direct bilirubin": "liver", "indirect bilirubin": "liver",
    # Kidney
    "creatinine": "kidney", "bun": "kidney", "urea": "kidney",
    "egfr": "kidney", "protein urine": "kidney",
    "microalbumin": "kidney", "cystatin": "kidney",
    # Heart
    "troponin": "heart", "bnp": "heart", "nt-probnp": "heart",
    "ck-mb": "heart", "ldh": "heart", "myoglobin": "heart",
    # Thyroid
    "tsh": "thyroid", "t3": "thyroid", "t4": "thyroid",
    "free t3": "thyroid", "free t4": "thyroid",
    # Pancreas
    "glucose": "pancreas", "hba1c": "pancreas", "hemoglobin a1c": "pancreas",
    "insulin": "pancreas", "amylase": "pancreas", "lipase": "pancreas",
    # Lungs
    "pco2": "lungs", "po2": "lungs", "o2 sat": "lungs", "spo2": "lungs",
    "bicarbonate": "lungs",
    # Blood / bone marrow
    "wbc": "blood", "rbc": "blood", "hemoglobin": "blood",
    "hematocrit": "blood", "platelets": "blood", "mcv": "blood",
    "mch": "blood", "mchc": "blood", "rdw": "blood",
    "neutrophils": "blood", "lymphocytes": "blood", "monocytes": "blood",
    "eosinophils": "blood", "basophils": "blood", "reticulocytes": "blood",
    "esr": "blood", "crp": "blood", "ferritin": "blood", "iron": "blood",
    # Bone / calcium
    "calcium": "bone", "phosphorus": "bone", "vitamin d": "bone",
    "pth": "bone", "magnesium": "bone",
    # Electrolytes (general / blood)
    "sodium": "blood", "potassium": "blood", "chloride": "blood",
    "co2": "blood",
    # Arteries / vascular
    "d-dimer": "arteries", "fibrinogen": "arteries",
    "inr": "arteries", "prothrombin time": "arteries", "ptt": "arteries", "aptt": "arteries",
    "homocysteine": "arteries", "lipoprotein a": "arteries",
    "ldl": "arteries", "hdl": "arteries", "triglycerides": "arteries",
    "total cholesterol": "arteries",
    # Immune / infectious disease
    "western blot": "immune", "hiv": "immune", "hiv antibody": "immune",
    "hiv antigen": "immune", "hiv viral load": "immune", "cd4": "immune",
    "covid": "immune", "sars-cov": "immune", "covid pcr": "immune",
    "malaria": "immune", "thick smear": "immune", "thin smear": "immune",
    "lyme": "immune", "borrelia": "immune",
    "hepatitis": "immune", "hbsag": "immune", "anti-hbs": "immune",
    "anti-hcv": "immune", "hcv rna": "immune",
    "rpr": "immune", "vdrl": "immune", "fta-abs": "immune",
    "tb test": "immune", "quantiferon": "immune", "igra": "immune", "ppd": "immune",
    "ana": "immune", "anti-dsdna": "immune",
    "complement": "immune", "c3": "immune", "c4": "immune",
    "immunoglobulin": "immune", "iga": "immune", "igm": "immune", "igg": "immune",
    "procalcitonin": "immune", "blood culture": "immune",
    # Reproductive
    "psa": "reproductive", "prostate specific": "reproductive",
    "testosterone": "reproductive", "free testosterone": "reproductive",
    "estrogen": "reproductive", "estradiol": "reproductive",
    "progesterone": "reproductive", "lh": "reproductive", "fsh": "reproductive",
    "hcg": "reproductive", "beta hcg": "reproductive",
    "prolactin": "reproductive", "inhibin": "reproductive",
    "semen": "reproductive", "sperm": "reproductive",
    "pap": "reproductive", "ca-125": "reproductive", "ca 125": "reproductive",
    "afp": "reproductive", "alpha fetoprotein": "reproductive",
    # Endocrine (non-thyroid)
    "cortisol": "endocrine", "acth": "endocrine", "aldosterone": "endocrine",
    "renin": "endocrine", "dhea": "endocrine", "dhea-s": "endocrine",
    "growth hormone": "endocrine", "igf-1": "endocrine", "igf1": "endocrine",
    "catecholamine": "endocrine", "metanephrine": "endocrine",
    "vanillylmandelic": "endocrine", "vma": "endocrine",
    "5-hiaa": "endocrine", "chromogranin": "endocrine",
    "adrenal": "endocrine", "pituitary": "endocrine",
    # Rheumatology
    "rheumatoid factor": "rheumatology", "anti-ccp": "rheumatology",
    "uric acid": "rheumatology", "sed rate": "rheumatology",
    "anti-smith": "rheumatology", "anti-rnp": "rheumatology",
    "anti-scl-70": "rheumatology", "anti-jo-1": "rheumatology",
    "anca": "rheumatology", "hla-b27": "rheumatology",
    # Gastrointestinal
    "stool": "gi", "fecal": "gi", "h pylori": "gi", "helicobacter": "gi",
    "celiac": "gi", "tissue transglutaminase": "gi", "ttg": "gi",
    "gliadin": "gi", "calprotectin": "gi", "occult blood": "gi",
    "fecal fat": "gi", "elastase": "gi",
    # Skin
    "skin biopsy": "skin", "dermatitis": "skin", "melanoma": "skin",
    "fungal culture skin": "skin", "wound culture": "skin",
    # Urinary
    "urinalysis": "urinary", "urine culture": "urinary", "uti": "urinary",
    "urine protein": "urinary", "urine glucose": "urinary",
    "urine ketones": "urinary", "urine blood": "urinary",
    "urine ph": "urinary", "specific gravity": "urinary",
    "urine leukocyte": "urinary", "urine nitrite": "urinary",
    # Genomic / pharmacogenomic
    "cyp2d6": "genomic", "cyp2c19": "genomic", "cyp3a4": "genomic",
    "brca": "genomic", "kras": "genomic", "egfr mutation": "genomic",
    "braf": "genomic", "her2": "genomic", "msi": "genomic",
    "pharmacogenomic": "genomic", "genetic": "genomic",
}

# Radiology body_region values already match our region keys in most cases.
# This map normalises any outliers.
RADIOLOGY_REGION_NORMALISE: Dict[str, str] = {
    "chest": "lungs",
    "thorax": "lungs",
    "abdomen": "liver",  # default abdominal to liver region
    "pelvis": "kidney",
    "head": "brain",
    "skull": "brain",
    "spine": "spine",
    "extremity": "bone",
    "neck": "thyroid",
    "vascular": "arteries",
    "arterial": "arteries",
    "aorta": "arteries",
    "nervous": "nerves",
    "neural": "nerves",
    "spinal cord": "nerves",
    "infectious": "immune",
    "immune": "immune",
    "reproductive": "reproductive",
    "ovarian": "reproductive",
    "uterine": "reproductive",
    "testicular": "reproductive",
    "prostate": "reproductive",
    "endocrine": "endocrine",
    "adrenal": "endocrine",
    "pituitary": "endocrine",
    # New regions
    "gastrointestinal": "gi",
    "stomach": "gi",
    "colon": "gi",
    "intestine": "gi",
    "bowel": "gi",
    "esophagus": "gi",
    "rectal": "gi",
    "appendix": "gi",
    "skin": "skin",
    "dermal": "skin",
    "subcutaneous": "skin",
    "urinary": "urinary",
    "bladder": "urinary",
    "urethra": "urinary",
    "rheumatology": "rheumatology",
    "joint": "rheumatology",
    "synovial": "rheumatology",
}

# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------

def _lab_flag_to_severity(flag: Optional[str]) -> str:
    """Map a StructuredLabValue.flag to a severity level."""
    if not flag:
        return "normal"
    flag = flag.upper()
    if "CRITICAL" in flag:
        return "critical"
    if flag in ("HIGH", "LOW"):
        return "abnormal"
    return "normal"


SEVERITY_RANK = {"normal": 0, "caution": 1, "abnormal": 2, "critical": 3}
SEVERITY_COLOR = {
    "normal": "#4CAF50",
    "caution": "#FFEB3B",
    "abnormal": "#FF9800",
    "critical": "#F44336",
}

# ---------------------------------------------------------------------------
# SVG layout constants
# ---------------------------------------------------------------------------
# On-body organ ellipses (rendered on the silhouette)
ON_BODY_REGIONS: Dict[str, dict] = {
    "brain":    {"cx": 130, "cy": 52,  "rx": 30, "ry": 25, "label": "Brain"},
    "thyroid":  {"cx": 130, "cy": 115, "rx": 14, "ry": 10, "label": "Thyroid"},
    "lungs":    {"cx": 130, "cy": 175, "rx": 48, "ry": 35, "label": "Lungs",  "label_side": "left"},
    "heart":    {"cx": 148, "cy": 200, "rx": 16, "ry": 16, "label": "Heart",  "label_side": "right"},
    "liver":    {"cx": 105, "cy": 255, "rx": 28, "ry": 18, "label": "Liver"},
    "pancreas": {"cx": 150, "cy": 275, "rx": 20, "ry": 10, "label": "Pancreas"},
    "kidney":   {"cx": 130, "cy": 305, "rx": 38, "ry": 12, "label": "Kidneys"},
}

# Spine: segmented vertebrae column to the right of the body
SPINE_CONFIG = {
    "x": 222,        # left edge of vertebrae column
    "top": 105,      # top of first vertebra (neck level)
    "width": 14,     # vertebra width
    "height": 10,    # vertebra height
    "gap": 2,        # gap between vertebrae
    "count": 16,     # number of vertebrae segments
}

# System circles in a 4×3 grid below the body
SYSTEM_CIRCLES: List[dict] = [
    # Row 1
    {"id": "blood",     "label": "Blood"},
    {"id": "bone",      "label": "Bone"},
    {"id": "arteries",  "label": "Arteries"},
    {"id": "nerves",    "label": "Nerves"},
    # Row 2
    {"id": "immune",    "label": "Immune"},
    {"id": "reproductive", "label": "Repro"},
    {"id": "endocrine", "label": "Endocrine"},
    {"id": "gi",        "label": "GI"},
    # Row 3
    {"id": "skin",      "label": "Skin"},
    {"id": "urinary",   "label": "Urinary"},
    {"id": "rheumatology", "label": "Rheumatol"},
    {"id": "genomic",   "label": "Genomic"},
]

GRID_COLS = 4
GRID_START_Y = 560
GRID_COL_SPACING = 55
GRID_ROW_SPACING = 50
GRID_RADIUS = 18
GRID_START_X = 130 - (GRID_COLS - 1) * GRID_COL_SPACING // 2  # centered

# Combined set of all valid region IDs (for radiology lookup)
ALL_REGION_IDS = (
    set(ON_BODY_REGIONS.keys())
    | {"spine"}
    | {s["id"] for s in SYSTEM_CIRCLES}
)


def _build_svg(region_severities: Dict[str, str],
               mass_regions: List[str],
               anatomical_regions: List[str]) -> str:
    """Return an inline SVG string for the body map."""
    parts: List[str] = []
    parts.append(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 260 780" '
        'width="260" height="780" style="font-family:Arial,sans-serif;">'
    )

    # Background silhouette — taller torso + two separate legs
    parts.append(
        '<path d="M130 20 C160 20 170 40 170 65 C170 85 160 95 155 105 '
        'L175 120 L195 150 L210 220 L200 230 L180 200 L175 230 '
        'L180 350 '
        'L140 350 L140 350 '
        'L120 350 '
        'L80 350 '
        'L85 230 L80 200 L60 230 L50 220 '
        'L65 150 L85 120 L105 105 C100 95 90 85 90 65 '
        'C90 40 100 20 130 20 Z" '
        'fill="#E8E8E8" stroke="#BDBDBD" stroke-width="1.5" />'
    )
    # Left leg
    parts.append(
        '<path d="M80 350 L85 350 L115 350 L120 350 '
        'L110 480 L100 495 L85 495 L75 480 Z" '
        'fill="#E8E8E8" stroke="#BDBDBD" stroke-width="1.5" />'
    )
    # Right leg
    parts.append(
        '<path d="M140 350 L145 350 L175 350 L180 350 '
        'L185 480 L175 495 L160 495 L150 480 Z" '
        'fill="#E8E8E8" stroke="#BDBDBD" stroke-width="1.5" />'
    )

    # --- On-body organ ellipses ---
    for region_id, geo in ON_BODY_REGIONS.items():
        severity = region_severities.get(region_id, "normal")
        color = SEVERITY_COLOR.get(severity, SEVERITY_COLOR["normal"])
        opacity = "0.15" if severity == "normal" else "0.55"
        parts.append(
            f'<ellipse id="region_{region_id}" '
            f'cx="{geo["cx"]}" cy="{geo["cy"]}" '
            f'rx="{geo["rx"]}" ry="{geo["ry"]}" '
            f'fill="{color}" fill-opacity="{opacity}" '
            f'stroke="{color}" stroke-width="1.5" />'
        )
        # Label — use label_side if specified to avoid overlaps
        label_side = geo.get("label_side")
        if label_side == "left":
            lx = geo["cx"] - geo["rx"] - 4
            ly = geo["cy"] + 4
            anchor = "end"
        elif label_side == "right":
            lx = geo["cx"] + geo["rx"] + 4
            ly = geo["cy"] + 4
            anchor = "start"
        else:
            lx = geo["cx"]
            ly = geo["cy"] + geo["ry"] + 12
            anchor = "middle"
        parts.append(
            f'<text x="{lx}" y="{ly}" '
            f'text-anchor="{anchor}" font-size="9" fill="#555">'
            f'{html.escape(geo["label"])}</text>'
        )
        # Mass icon: red X spanning the organ (70% inset so it stays inside)
        if region_id in mass_regions:
            inset = 0.70
            dx = geo["rx"] * inset
            dy = geo["ry"] * inset
            cx, cy = geo["cx"], geo["cy"]
            parts.append(
                f'<line x1="{cx - dx}" y1="{cy - dy}" x2="{cx + dx}" y2="{cy + dy}" '
                f'stroke="#F44336" stroke-width="2.5" />'
                f'<line x1="{cx - dx}" y1="{cy + dy}" x2="{cx + dx}" y2="{cy - dy}" '
                f'stroke="#F44336" stroke-width="2.5" />'
            )
        # Anatomical finding icon: orange triangle
        if region_id in anatomical_regions:
            tx = geo["cx"] - geo["rx"] + 4
            ty = geo["cy"] - geo["ry"] + 4
            parts.append(
                f'<polygon points="{tx},{ty+10} {tx-7},{ty-3} {tx+7},{ty-3}" '
                f'fill="#FF9800" stroke="#E65100" stroke-width="1" />'
            )

    # --- Spine: segmented vertebrae to the right of the body ---
    sc = SPINE_CONFIG
    spine_severity = region_severities.get("spine", "normal")
    spine_color = SEVERITY_COLOR.get(spine_severity, SEVERITY_COLOR["normal"])
    spine_opacity = "0.15" if spine_severity == "normal" else "0.55"
    for v in range(sc["count"]):
        vy = sc["top"] + v * (sc["height"] + sc["gap"])
        parts.append(
            f'<rect x="{sc["x"]}" y="{vy}" width="{sc["width"]}" height="{sc["height"]}" '
            f'rx="3" ry="3" fill="{spine_color}" fill-opacity="{spine_opacity}" '
            f'stroke="{spine_color}" stroke-width="1" />'
        )
        parts.append(
            f'<rect x="{sc["x"]}" y="{vy}" width="{sc["width"]}" height="{sc["height"]}" '
            f'rx="3" ry="3" fill="none" stroke="#CCC" stroke-width="0.5" />'
        )
    spine_bottom = sc["top"] + sc["count"] * (sc["height"] + sc["gap"])
    parts.append(
        f'<text x="{sc["x"] + sc["width"] // 2}" y="{spine_bottom + 10}" '
        f'text-anchor="middle" font-size="9" fill="#555">Spine</text>'
    )

    # --- Divider line ---
    parts.append(
        '<line x1="30" y1="520" x2="230" y2="520" '
        'stroke="#DDD" stroke-width="1" stroke-dasharray="4,3" />'
    )
    parts.append(
        '<text x="130" y="537" text-anchor="middle" font-size="10" '
        'font-weight="bold" fill="#555">Body Systems</text>'
    )

    # --- System circles grid (4×3) ---
    for i, sys_info in enumerate(SYSTEM_CIRCLES):
        row = i // GRID_COLS
        col = i % GRID_COLS
        cx = GRID_START_X + col * GRID_COL_SPACING
        cy = GRID_START_Y + row * GRID_ROW_SPACING
        region_id = sys_info["id"]

        severity = region_severities.get(region_id, "normal")
        color = SEVERITY_COLOR.get(severity, SEVERITY_COLOR["normal"])
        opacity = "0.15" if severity == "normal" else "0.55"

        parts.append(
            f'<circle id="region_{region_id}" cx="{cx}" cy="{cy}" r="{GRID_RADIUS}" '
            f'fill="{color}" fill-opacity="{opacity}" '
            f'stroke="{color}" stroke-width="1.5" />'
        )
        # Thin always-visible border
        parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{GRID_RADIUS}" '
            f'fill="none" stroke="#CCC" stroke-width="0.5" />'
        )
        # Label
        parts.append(
            f'<text x="{cx}" y="{cy + GRID_RADIUS + 12}" '
            f'text-anchor="middle" font-size="8" fill="#555">'
            f'{html.escape(sys_info["label"])}</text>'
        )
        # Mass icon on system circles: red X spanning the circle
        if region_id in mass_regions:
            inset = 0.70
            dx = GRID_RADIUS * inset
            dy = GRID_RADIUS * inset
            parts.append(
                f'<line x1="{cx - dx}" y1="{cy - dy}" x2="{cx + dx}" y2="{cy + dy}" '
                f'stroke="#F44336" stroke-width="2.5" />'
                f'<line x1="{cx - dx}" y1="{cy + dy}" x2="{cx + dx}" y2="{cy - dy}" '
                f'stroke="#F44336" stroke-width="2.5" />'
            )
        # Anatomical finding icon on system circles
        if region_id in anatomical_regions:
            tx = cx - GRID_RADIUS + 4
            ty = cy - GRID_RADIUS + 4
            parts.append(
                f'<polygon points="{tx},{ty+10} {tx-7},{ty-3} {tx+7},{ty-3}" '
                f'fill="#FF9800" stroke="#E65100" stroke-width="1" />'
            )

    # --- Legend ---
    ly = 720
    for label, color in [("Normal", "#4CAF50"), ("Caution", "#FFEB3B"),
                          ("Alert", "#FF9800"), ("Critical", "#F44336")]:
        parts.append(
            f'<rect x="30" y="{ly}" width="12" height="12" rx="2" fill="{color}" />'
            f'<text x="46" y="{ly + 10}" font-size="9" fill="#555">{label}</text>'
        )
        ly += 16

    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Finding text → region/type helpers (used by tapestry to parse notes)
# ---------------------------------------------------------------------------
_TAPESTRY_REGION_KEYWORDS: Dict[str, List[str]] = {
    "brain": ["brain", "cerebr", "intracranial", "cranial"],
    "lungs": ["lung", "pulmonary", "pleural", "bronch", "thoracic", "chest", "pneumo", "mediastin"],
    "heart": ["heart", "cardiac", "coronary", "myocardial", "pericardial"],
    "liver": ["liver", "hepatic", "biliary", "gallbladder"],
    "kidney": ["kidney", "renal"],
    "thyroid": ["thyroid"],
    "pancreas": ["pancrea"],
    "spine": ["spine", "spinal", "vertebr", "lumbar", "cervical", "disc"],
    "bone": ["bone", "fracture", "skeletal", "femur", "tibia", "rib"],
    "blood": ["lymphoma", "leukemia", "lymph", "hodgkin", "myeloma", "anemia",
              "pancytopenia", "lymphadenopathy", "lymphaden"],
    "arteries": ["arteri", "vascular", "aorta", "aneurysm", "stenosis", "thrombosis"],
    "nerves": ["cauda equina", "spinal cord", "myelopath", "neuropath", "radiculopath"],
    "immune": ["infection", "abscess", "septic", "tuberculosis", "hiv"],
    "reproductive": ["ovari", "uterine", "prostat", "testicular", "breast", "cervical cancer"],
    "endocrine": ["adrenal", "pheochromocytoma", "pituitary", "cushing"],
    "gi": ["colon", "colonic", "intestin", "bowel", "gastric", "stomach", "esophag",
           "rectal", "rectum", "appendix", "duoden", "cecum", "sigmoid", "peritoneal"],
    "skin": ["skin", "dermal", "melanoma", "basal cell", "squamous cell skin"],
    "urinary": ["bladder", "urethra", "urinary", "cystitis"],
    "rheumatology": ["synovial", "arthritis", "gout", "rheumatoid", "lupus"],
}

_TAPESTRY_MASS_KEYWORDS = [
    "mass", "tumor", "tumour", "neoplasm", "lesion", "nodule", "carcinoma",
    "cancer", "malignant", "malignancy", "metasta", "lymphoma", "leukemia",
    "sarcoma", "melanoma", "adenocarcinoma", "invasive", "myeloma",
]

_TAPESTRY_ANATOMICAL_KEYWORDS = [
    "fracture", "collapse", "pneumothorax", "hemorrhage", "bleed",
    "aneurysm", "dissection", "stenosis", "occlusion", "thrombosis",
    "infection", "abscess", "inflammation",
]


def _region_from_text(text: str) -> Optional[str]:
    """Extract a tapestry region from free text."""
    text_lower = text.lower()
    for region, keywords in _TAPESTRY_REGION_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return region
    return None


def _is_mass_text(text: str) -> bool:
    """Check if text describes a mass/tumor/cancer."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in _TAPESTRY_MASS_KEYWORDS)


def _is_anatomical_text(text: str) -> bool:
    """Check if text describes an anatomical finding."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in _TAPESTRY_ANATOMICAL_KEYWORDS)

async def _gather_patient_summary(
    mongodb_client: Any,
    tenant_id: str,
    patient_id: int,
) -> str:
    """
    Compile ALL patient data from MongoDB into a single text block
    that MedGemma 27B can reason over for tapestry classification.
    """
    sections: List[str] = []

    # --- Lab values (flagged only — skip normals to save tokens) ---
    try:
        labs = await mongodb_client.get_patient_lab_history(
            tenant_id=tenant_id, patient_id=patient_id, limit=200,
        )
        lab_lines = []
        for lab in labs:
            flag = (lab.flag or "").upper()
            if flag and flag != "NORMAL":
                lab_lines.append(
                    f"  - {lab.test_name}: {lab.value} {lab.unit or ''} "
                    f"(flag: {flag})"
                )
        if lab_lines:
            sections.append("LAB VALUES (abnormal only):\n" + "\n".join(lab_lines[:60]))
    except Exception as e:
        logger.warning(f"Tapestry summary: lab fetch failed: {e}")

    # --- Radiology findings ---
    try:
        rad_findings = await mongodb_client.get_patient_radiology_findings(
            tenant_id=tenant_id, patient_id=patient_id,
        )
        if rad_findings:
            rad_lines = []
            for f in rad_findings[:40]:
                parts = []
                if f.get("finding_type"):
                    parts.append(f"type={f['finding_type']}")
                if f.get("body_region"):
                    parts.append(f"region={f['body_region']}")
                if f.get("notes"):
                    parts.append(f"notes: {f['notes']}")
                rad_lines.append("  - " + ", ".join(parts))
            sections.append("RADIOLOGY FINDINGS:\n" + "\n".join(rad_lines))
    except Exception as e:
        logger.warning(f"Tapestry summary: radiology fetch failed: {e}")

    # --- Processed report findings + analysis summaries ---
    try:
        report_findings = await mongodb_client.get_patient_report_findings(
            tenant_id=tenant_id, patient_id=patient_id,
        )
        if report_findings:
            rf_lines = [f"  - {text}" for text in report_findings[:40]]
            sections.append(
                "PROCESSED REPORT FINDINGS & ANALYSIS SUMMARIES:\n"
                + "\n".join(rf_lines)
            )
    except Exception as e:
        logger.warning(f"Tapestry summary: report findings fetch failed: {e}")

    # --- Patient history (recent reports + notes) ---
    try:
        history = await mongodb_client.get_patient_history(
            tenant_id=tenant_id, patient_id=patient_id, limit=10,
        )
        if history:
            hist_lines = []
            for h in history:
                hist_lines.append(
                    f"  - [{h['type']}] score={h.get('score',0)}: "
                    f"{h.get('summary','')[:200]}"
                )
            sections.append("PATIENT HISTORY:\n" + "\n".join(hist_lines))
    except Exception as e:
        logger.warning(f"Tapestry summary: history fetch failed: {e}")

    # --- Clinical notes (processed_notes analysis summaries) ---
    try:
        note_summaries = await mongodb_client.get_patient_note_summaries(
            tenant_id=tenant_id, patient_id=patient_id, limit=20,
        )
        if note_summaries:
            note_lines = [f"  - {text[:300]}" for text in note_summaries[:30]]
            sections.append("CLINICAL NOTES:\n" + "\n".join(note_lines))
    except Exception as e:
        logger.warning(f"Tapestry summary: notes fetch failed: {e}")

    return "\n\n".join(sections) if sections else ""


def _keyword_fallback(
    mongodb_labs: list,
    rad_findings: list,
    report_findings: List[str],
) -> tuple:
    """
    Keyword-based fallback classification (used when MedGemma is unavailable).
    Returns (region_severities, mass_regions, anatomical_regions).
    """
    region_severities: Dict[str, str] = {}
    mass_regions: List[str] = []
    anatomical_regions: List[str] = []

    # Labs
    for lab in mongodb_labs:
        test_key = (lab.test_name or "").lower().strip()
        region = None
        for pattern, rgn in LAB_TO_REGION.items():
            if pattern in test_key:
                region = rgn
                break
        if not region:
            continue
        severity = _lab_flag_to_severity(lab.flag)
        existing = region_severities.get(region, "normal")
        if SEVERITY_RANK.get(severity, 0) > SEVERITY_RANK.get(existing, 0):
            region_severities[region] = severity

    # Radiology
    for finding in rad_findings:
        body_region_raw = (finding.get("body_region") or "").lower().strip()
        finding_type = (finding.get("finding_type") or "").lower().strip()
        notes = (finding.get("notes") or "").lower().strip()
        combined_text = f"{finding_type} {notes}"

        region = RADIOLOGY_REGION_NORMALISE.get(body_region_raw, body_region_raw)
        if region not in ALL_REGION_IDS:
            region = _region_from_text(combined_text)
        if not region or region not in ALL_REGION_IDS:
            continue

        if _is_mass_text(combined_text):
            mass_regions.append(region)
            region_severities[region] = "critical"
        elif _is_anatomical_text(combined_text):
            anatomical_regions.append(region)
            existing = region_severities.get(region, "normal")
            if SEVERITY_RANK.get("abnormal", 0) > SEVERITY_RANK.get(existing, 0):
                region_severities[region] = "abnormal"
        else:
            existing = region_severities.get(region, "normal")
            if SEVERITY_RANK.get("caution", 0) > SEVERITY_RANK.get(existing, 0):
                region_severities[region] = "caution"

    # Report findings
    for finding_text in report_findings:
        region = _region_from_text(finding_text)
        if not region or region not in ALL_REGION_IDS:
            continue
        if _is_mass_text(finding_text):
            mass_regions.append(region)
            region_severities[region] = "critical"
        elif _is_anatomical_text(finding_text):
            anatomical_regions.append(region)
            existing = region_severities.get(region, "normal")
            if SEVERITY_RANK.get("abnormal", 0) > SEVERITY_RANK.get(existing, 0):
                region_severities[region] = "abnormal"
        else:
            existing = region_severities.get(region, "normal")
            if SEVERITY_RANK.get("caution", 0) > SEVERITY_RANK.get(existing, 0):
                region_severities[region] = "caution"

    return region_severities, list(set(mass_regions)), list(set(anatomical_regions))


async def generate_tapestry(
    mongodb_client: Any,
    tenant_id: str,
    patient_id: int,
    medgemma_27b: Any = None,
) -> str:
    """
    Generate a colour-coded SVG body map for a patient.

    PRIMARY path: Ask MedGemma 27B to classify affected regions from
    the full patient record (labs, radiology, reports, notes).

    FALLBACK path: Keyword-based classification if the model call fails.

    Returns an HTML string (wrapped SVG) ready to be injected into an email.
    Returns empty string on any error so the email still sends.
    """
    try:
        region_severities: Dict[str, str] = {}
        mass_regions: List[str] = []
        anatomical_regions: List[str] = []
        used_model = False

        # --- Try MedGemma 27B classification first ---
        if medgemma_27b:
            try:
                patient_summary = await _gather_patient_summary(
                    mongodb_client, tenant_id, patient_id,
                )
                if patient_summary:
                    result = await medgemma_27b.classify_tapestry_regions(
                        patient_summary=patient_summary,
                    )
                    for item in result.get("regions", []):
                        region = item["region"]
                        severity = item["severity"]
                        existing = region_severities.get(region, "normal")
                        if SEVERITY_RANK.get(severity, 0) > SEVERITY_RANK.get(existing, 0):
                            region_severities[region] = severity
                        if item.get("is_mass"):
                            mass_regions.append(region)
                            region_severities[region] = "critical"
                        if item.get("is_anatomical"):
                            anatomical_regions.append(region)
                    used_model = True
                    logger.info(
                        f"Tapestry: MedGemma classified {len(result.get('regions', []))} "
                        f"regions for patient {patient_id}"
                    )
            except Exception as e:
                logger.warning(
                    f"Tapestry: MedGemma classification failed for patient "
                    f"{patient_id}, falling back to keywords: {e}"
                )

        # --- Fallback: keyword-based classification ---
        if not used_model:
            logger.info(f"Tapestry: using keyword fallback for patient {patient_id}")
            labs = await mongodb_client.get_patient_lab_history(
                tenant_id=tenant_id, patient_id=patient_id, limit=200,
            )
            rad_findings = await mongodb_client.get_patient_radiology_findings(
                tenant_id=tenant_id, patient_id=patient_id,
            )
            report_findings: List[str] = []
            try:
                report_findings = await mongodb_client.get_patient_report_findings(
                    tenant_id=tenant_id, patient_id=patient_id,
                )
            except Exception:
                pass

            region_severities, mass_regions, anatomical_regions = _keyword_fallback(
                labs, rad_findings, report_findings,
            )

        # Deduplicate
        mass_regions = list(set(mass_regions))
        anatomical_regions = list(set(anatomical_regions))

        svg = _build_svg(region_severities, mass_regions, anatomical_regions)

        classification_note = (
            "AI-classified body map (MedGemma 27B)"
            if used_model
            else "Colour-coded body map based on lab values and radiology findings."
        )

        return f"""
        <div style="margin-top: 30px; padding: 20px; border: 1px solid #E0E0E0; border-radius: 8px; background: #FAFAFA;">
            <h3 style="margin: 0 0 10px 0; color: #333;">Patient Tapestry</h3>
            <p style="margin: 0 0 15px 0; color: #666; font-size: 12px;">
                {classification_note}
            </p>
            <div style="text-align: center;">
                {svg}
            </div>
        </div>
        """

    except Exception as e:
        logger.error(f"Tapestry generation failed for patient {patient_id}: {e}")
        return ""
