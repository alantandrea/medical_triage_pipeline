/**
 * Generate Medical Report Lambda
 *
 * Generates realistic medical reports (lab, radiology, pathology) for patients.
 * Uses real medical images from public datasets (NIH ChestX-ray14, LIDC-IDRI, etc.)
 * stored in S3 instead of AI-generated synthetic images.
 *
 * Image Sources (all free, open license):
 * - NIH ChestX-ray14: CC0 Public Domain
 * - LIDC-IDRI: CC BY 3.0
 * - IXI Dataset: CC BY-SA 3.0
 */

const { DynamoDBClient } = require('@aws-sdk/client-dynamodb');
const { DynamoDBDocumentClient, ScanCommand, GetCommand, PutCommand } = require('@aws-sdk/lib-dynamodb');
const { S3Client, PutObjectCommand, GetObjectCommand, ListObjectsV2Command } = require('@aws-sdk/client-s3');
const { v4: uuidv4 } = require('uuid');
const PDFDocument = require('pdfkit');

const dynamoClient = new DynamoDBClient({});
const docClient = DynamoDBDocumentClient.from(dynamoClient);
const s3Client = new S3Client({});

// Report types
const REPORT_TYPES = ['lab', 'xray', 'ct', 'mri', 'mra', 'pet', 'path'];

// Severity distribution: 40% normal, 25% minor, 20% major, 15% critical
function getSeverity() {
  const rand = Math.random();
  if (rand < 0.40) return 'normal';
  if (rand < 0.65) return 'minor';
  if (rand < 0.85) return 'major';
  return 'critical';
}

// Lab sources
const LAB_SOURCES = ['Quest Diagnostics', 'LabCorp', 'BioReference Laboratories', 'ARUP Laboratories', 'Mayo Clinic Laboratories'];
// Radiology sources
const RADIOLOGY_SOURCES = ['Regional Medical Imaging Center', 'University Hospital Radiology', 'Advanced Diagnostic Imaging', 'Premier Radiology Associates', 'Metropolitan Imaging Center'];
// Pathology sources
const PATHOLOGY_SOURCES = ['PathGroup', 'AmeriPath', 'Dianon Pathology', 'Aurora Diagnostics', 'Quest Diagnostics Pathology'];

function randomElement(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

function calculateAge(dob) {
  const birthDate = new Date(dob);
  const today = new Date();
  let age = today.getFullYear() - birthDate.getFullYear();
  const monthDiff = today.getMonth() - birthDate.getMonth();
  if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birthDate.getDate())) {
    age--;
  }
  return age;
}

// ==================== LAB TEST GENERATORS ====================

const labTests = {
  BMP: {
    name: 'Basic Metabolic Panel',
    tests: [
      { name: 'Glucose', unit: 'mg/dL', normalLow: 70, normalHigh: 100, minorLow: 60, minorHigh: 126, majorLow: 40, majorHigh: 200 },
      { name: 'BUN', unit: 'mg/dL', normalLow: 7, normalHigh: 20, minorLow: 5, minorHigh: 30, majorLow: 3, majorHigh: 50 },
      { name: 'Creatinine', unit: 'mg/dL', normalLow: 0.7, normalHigh: 1.3, minorLow: 0.5, minorHigh: 2.0, majorLow: 0.3, majorHigh: 4.0 },
      { name: 'Sodium', unit: 'mEq/L', normalLow: 136, normalHigh: 145, minorLow: 130, minorHigh: 150, majorLow: 120, majorHigh: 160 },
      { name: 'Potassium', unit: 'mEq/L', normalLow: 3.5, normalHigh: 5.0, minorLow: 3.0, minorHigh: 5.5, majorLow: 2.5, majorHigh: 6.5 },
      { name: 'Chloride', unit: 'mEq/L', normalLow: 98, normalHigh: 106, minorLow: 94, minorHigh: 110, majorLow: 90, majorHigh: 115 },
      { name: 'CO2', unit: 'mEq/L', normalLow: 23, normalHigh: 29, minorLow: 20, minorHigh: 32, majorLow: 15, majorHigh: 40 },
      { name: 'Calcium', unit: 'mg/dL', normalLow: 8.5, normalHigh: 10.5, minorLow: 8.0, minorHigh: 11.0, majorLow: 7.0, majorHigh: 13.0 }
    ]
  },
  CBC: {
    name: 'Complete Blood Count',
    tests: [
      { name: 'WBC', unit: 'K/uL', normalLow: 4.5, normalHigh: 11.0, minorLow: 3.5, minorHigh: 15.0, majorLow: 2.0, majorHigh: 30.0 },
      { name: 'RBC', unit: 'M/uL', normalLow: 4.5, normalHigh: 5.5, minorLow: 4.0, minorHigh: 6.0, majorLow: 3.0, majorHigh: 7.0 },
      { name: 'Hemoglobin', unit: 'g/dL', normalLow: 12.0, normalHigh: 17.5, minorLow: 10.0, minorHigh: 19.0, majorLow: 7.0, majorHigh: 22.0 },
      { name: 'Hematocrit', unit: '%', normalLow: 36, normalHigh: 50, minorLow: 32, minorHigh: 55, majorLow: 25, majorHigh: 60 },
      { name: 'MCV', unit: 'fL', normalLow: 80, normalHigh: 100, minorLow: 70, minorHigh: 110, majorLow: 60, majorHigh: 120 },
      { name: 'MCH', unit: 'pg', normalLow: 27, normalHigh: 33, minorLow: 24, minorHigh: 36, majorLow: 20, majorHigh: 40 },
      { name: 'MCHC', unit: 'g/dL', normalLow: 32, normalHigh: 36, minorLow: 30, minorHigh: 38, majorLow: 28, majorHigh: 40 },
      { name: 'Platelets', unit: 'K/uL', normalLow: 150, normalHigh: 400, minorLow: 100, minorHigh: 500, majorLow: 50, majorHigh: 800 }
    ]
  },
  LIPID: {
    name: 'Lipid Panel',
    tests: [
      { name: 'Total Cholesterol', unit: 'mg/dL', normalLow: 0, normalHigh: 200, minorLow: 0, minorHigh: 239, majorLow: 0, majorHigh: 300 },
      { name: 'Triglycerides', unit: 'mg/dL', normalLow: 0, normalHigh: 150, minorLow: 0, minorHigh: 199, majorLow: 0, majorHigh: 500 },
      { name: 'HDL Cholesterol', unit: 'mg/dL', normalLow: 40, normalHigh: 200, minorLow: 35, minorHigh: 200, majorLow: 25, majorHigh: 200 },
      { name: 'LDL Cholesterol', unit: 'mg/dL', normalLow: 0, normalHigh: 100, minorLow: 0, minorHigh: 159, majorLow: 0, majorHigh: 190 },
      { name: 'VLDL', unit: 'mg/dL', normalLow: 5, normalHigh: 40, minorLow: 0, minorHigh: 50, majorLow: 0, majorHigh: 100 }
    ]
  },
  A1C: {
    name: 'Hemoglobin A1C',
    tests: [
      { name: 'Hemoglobin A1C', unit: '%', normalLow: 4.0, normalHigh: 5.6, minorLow: 3.5, minorHigh: 6.4, majorLow: 3.0, majorHigh: 10.0 }
    ]
  },
  THYROID: {
    name: 'Thyroid Panel',
    tests: [
      { name: 'TSH', unit: 'mIU/L', normalLow: 0.4, normalHigh: 4.0, minorLow: 0.1, minorHigh: 8.0, majorLow: 0.01, majorHigh: 20.0 },
      { name: 'Free T4', unit: 'ng/dL', normalLow: 0.8, normalHigh: 1.8, minorLow: 0.5, minorHigh: 2.5, majorLow: 0.2, majorHigh: 5.0 },
      { name: 'Free T3', unit: 'pg/mL', normalLow: 2.3, normalHigh: 4.2, minorLow: 1.8, minorHigh: 5.0, majorLow: 1.0, majorHigh: 8.0 }
    ]
  },
  PSA: {
    name: 'Prostate-Specific Antigen',
    tests: [
      { name: 'PSA, Total', unit: 'ng/mL', normalLow: 0, normalHigh: 4.0, minorLow: 0, minorHigh: 10.0, majorLow: 0, majorHigh: 20.0 }
    ]
  },
  LIVER: {
    name: 'Liver Function Panel',
    tests: [
      { name: 'AST (SGOT)', unit: 'U/L', normalLow: 10, normalHigh: 40, minorLow: 5, minorHigh: 80, majorLow: 0, majorHigh: 500 },
      { name: 'ALT (SGPT)', unit: 'U/L', normalLow: 7, normalHigh: 56, minorLow: 5, minorHigh: 100, majorLow: 0, majorHigh: 500 },
      { name: 'Alkaline Phosphatase', unit: 'U/L', normalLow: 44, normalHigh: 147, minorLow: 30, minorHigh: 200, majorLow: 20, majorHigh: 500 },
      { name: 'Bilirubin, Total', unit: 'mg/dL', normalLow: 0.1, normalHigh: 1.2, minorLow: 0.1, minorHigh: 2.5, majorLow: 0.1, majorHigh: 10.0 },
      { name: 'Albumin', unit: 'g/dL', normalLow: 3.5, normalHigh: 5.0, minorLow: 2.8, minorHigh: 5.5, majorLow: 2.0, majorHigh: 6.0 },
      { name: 'Total Protein', unit: 'g/dL', normalLow: 6.0, normalHigh: 8.3, minorLow: 5.0, minorHigh: 9.0, majorLow: 4.0, majorHigh: 10.0 }
    ]
  },
  CMP: {
    name: 'Comprehensive Metabolic Panel',
    tests: [
      { name: 'Glucose', unit: 'mg/dL', normalLow: 70, normalHigh: 100, minorLow: 60, minorHigh: 126, majorLow: 40, majorHigh: 200 },
      { name: 'BUN', unit: 'mg/dL', normalLow: 7, normalHigh: 20, minorLow: 5, minorHigh: 30, majorLow: 3, majorHigh: 50 },
      { name: 'Creatinine', unit: 'mg/dL', normalLow: 0.7, normalHigh: 1.3, minorLow: 0.5, minorHigh: 2.0, majorLow: 0.3, majorHigh: 4.0 },
      { name: 'Sodium', unit: 'mEq/L', normalLow: 136, normalHigh: 145, minorLow: 130, minorHigh: 150, majorLow: 120, majorHigh: 160 },
      { name: 'Potassium', unit: 'mEq/L', normalLow: 3.5, normalHigh: 5.0, minorLow: 3.0, minorHigh: 5.5, majorLow: 2.5, majorHigh: 6.5 },
      { name: 'Chloride', unit: 'mEq/L', normalLow: 98, normalHigh: 106, minorLow: 94, minorHigh: 110, majorLow: 90, majorHigh: 115 },
      { name: 'CO2', unit: 'mEq/L', normalLow: 23, normalHigh: 29, minorLow: 20, minorHigh: 32, majorLow: 15, majorHigh: 40 },
      { name: 'Calcium', unit: 'mg/dL', normalLow: 8.5, normalHigh: 10.5, minorLow: 8.0, minorHigh: 11.0, majorLow: 7.0, majorHigh: 13.0 },
      { name: 'AST (SGOT)', unit: 'U/L', normalLow: 10, normalHigh: 40, minorLow: 5, minorHigh: 80, majorLow: 0, majorHigh: 200 },
      { name: 'ALT (SGPT)', unit: 'U/L', normalLow: 7, normalHigh: 56, minorLow: 5, minorHigh: 100, majorLow: 0, majorHigh: 200 },
      { name: 'Alkaline Phosphatase', unit: 'U/L', normalLow: 44, normalHigh: 147, minorLow: 30, minorHigh: 200, majorLow: 20, majorHigh: 300 },
      { name: 'Bilirubin, Total', unit: 'mg/dL', normalLow: 0.1, normalHigh: 1.2, minorLow: 0.1, minorHigh: 2.5, majorLow: 0.1, majorHigh: 5.0 },
      { name: 'Albumin', unit: 'g/dL', normalLow: 3.5, normalHigh: 5.0, minorLow: 2.8, minorHigh: 5.5, majorLow: 2.0, majorHigh: 6.0 },
      { name: 'Total Protein', unit: 'g/dL', normalLow: 6.0, normalHigh: 8.3, minorLow: 5.0, minorHigh: 9.0, majorLow: 4.0, majorHigh: 10.0 }
    ]
  }
};

function generateLabValue(test, severity) {
  let value;
  const decimals = test.normalLow < 10 ? 1 : 0;

  switch (severity) {
    case 'normal':
      value = test.normalLow + Math.random() * (test.normalHigh - test.normalLow);
      break;
    case 'minor':
      if (Math.random() < 0.5) {
        value = test.minorLow + Math.random() * (test.normalLow - test.minorLow);
      } else {
        value = test.normalHigh + Math.random() * (test.minorHigh - test.normalHigh);
      }
      break;
    case 'major':
      if (Math.random() < 0.5) {
        value = test.majorLow + Math.random() * (test.minorLow - test.majorLow);
      } else {
        value = test.minorHigh + Math.random() * (test.majorHigh - test.minorHigh);
      }
      break;
    case 'critical':
      if (Math.random() < 0.5) {
        value = test.majorLow * 0.7;
      } else {
        value = test.majorHigh * 1.3;
      }
      break;
  }

  return Number(value.toFixed(decimals));
}

/**
 * Generate physiologically coherent CBC results.
 * Primary values (WBC, RBC, Hemoglobin, Platelets) are generated from severity ranges.
 * Derived values (Hematocrit, MCV, MCH, MCHC) are calculated from the primaries:
 *   Hematocrit ≈ Hemoglobin × 3
 *   MCV = (Hematocrit / RBC) × 10
 *   MCH = (Hemoglobin / RBC) × 10
 *   MCHC = (Hemoglobin / Hematocrit) × 100
 */
function generateCBCResults(severity) {
  const panel = labTests.CBC;
  const testMap = {};
  panel.tests.forEach(t => { testMap[t.name] = t; });

  // Generate primary values based on severity
  const testSev = () => Math.random() < 0.7 ? severity : getSeverity();
  const wbc = generateLabValue(testMap['WBC'], testSev());
  const rbc = generateLabValue(testMap['RBC'], testSev());
  const hgb = generateLabValue(testMap['Hemoglobin'], testSev());
  const platelets = generateLabValue(testMap['Platelets'], testSev());

  // Derive calculated values with small physiological variation (±3%)
  const jitter = () => 0.97 + Math.random() * 0.06;
  const hct = Number((hgb * 3.0 * jitter()).toFixed(0));
  const mcv = Number(((hct / rbc) * 10 * jitter()).toFixed(0));
  const mch = Number(((hgb / rbc) * 10 * jitter()).toFixed(1));
  const mchc = Number(((hgb / hct) * 100 * jitter()).toFixed(0));

  const makeResult = (test, value) => {
    const flag = value < test.normalLow ? 'L' : (value > test.normalHigh ? 'H' : '');
    return {
      name: test.name,
      value: value,
      unit: test.unit,
      reference: `${test.normalLow} - ${test.normalHigh}`,
      flag: flag
    };
  };

  return {
    panelName: panel.name,
    results: [
      makeResult(testMap['WBC'], wbc),
      makeResult(testMap['RBC'], rbc),
      makeResult(testMap['Hemoglobin'], hgb),
      makeResult(testMap['Hematocrit'], hct),
      makeResult(testMap['MCV'], mcv),
      makeResult(testMap['MCH'], mch),
      makeResult(testMap['MCHC'], mchc),
      makeResult(testMap['Platelets'], platelets),
    ]
  };
}

function generateLabResults(severity, patientSex = null) {
  let panelKeys = Object.keys(labTests);
  // PSA is only relevant for male patients
  if (patientSex === 'F') {
    panelKeys = panelKeys.filter(k => k !== 'PSA');
  }
  const panelKey = randomElement(panelKeys);

  // Use special coherent generator for CBC
  if (panelKey === 'CBC') {
    return generateCBCResults(severity);
  }

  const panel = labTests[panelKey];

  const results = panel.tests.map(test => {
    const testSeverity = Math.random() < 0.7 ? severity : getSeverity();
    const value = generateLabValue(test, testSeverity);
    const flag = value < test.normalLow ? 'L' : (value > test.normalHigh ? 'H' : '');

    return {
      name: test.name,
      value: value,
      unit: test.unit,
      reference: `${test.normalLow} - ${test.normalHigh}`,
      flag: flag
    };
  });

  return {
    panelName: panel.name,
    results: results
  };
}

// ==================== MEDICAL IMAGE RETRIEVAL ====================

/**
 * Get a real medical image from S3 bucket (populated from NIH ChestX-ray14 or similar datasets)
 * @param {string} reportType - Type of report (xray, ct, mri, etc.)
 * @param {string} severity - Severity level (normal, minor, major, critical)
 * @returns {Promise<Buffer|null>} Image buffer or null if not available
 */
async function getMedicalImage(reportType, severity) {
  const bucketName = process.env.MEDICAL_IMAGES_BUCKET;

  // Map report types to image modalities
  const modalityMap = {
    'xray': 'xray',
    'ct': 'ct',
    'mri': 'mri',
    'mra': 'mri',
    'pet': 'ct'
  };

  const modality = modalityMap[reportType] || 'xray';
  const prefix = `${modality}/${severity}/`;

  try {
    // List available images for this modality and severity
    const listResult = await s3Client.send(new ListObjectsV2Command({
      Bucket: bucketName,
      Prefix: prefix,
      MaxKeys: 100
    }));

    if (!listResult.Contents || listResult.Contents.length === 0) {
      console.warn(`No images found for ${modality}/${severity}, trying fallback`);
      // Fallback to normal severity
      return await getMedicalImageFallback(bucketName, modality);
    }

    // Select a random image
    const randomIndex = Math.floor(Math.random() * listResult.Contents.length);
    const selectedKey = listResult.Contents[randomIndex].Key;

    // Get the image
    const getResult = await s3Client.send(new GetObjectCommand({
      Bucket: bucketName,
      Key: selectedKey
    }));

    const imageBuffer = Buffer.from(await getResult.Body.transformToByteArray());

    console.log(`Retrieved medical image: ${selectedKey}`);

    return {
      buffer: imageBuffer,
      metadata: {
        source: 'medical_dataset',
        modality: modality,
        severity: severity,
        s3Key: selectedKey,
        license: 'CC0/CC-BY (Public Dataset)'
      }
    };
  } catch (error) {
    console.error('Error retrieving medical image:', error);
    return null;
  }
}

async function getMedicalImageFallback(bucketName, modality) {
  try {
    const listResult = await s3Client.send(new ListObjectsV2Command({
      Bucket: bucketName,
      Prefix: `${modality}/normal/`,
      MaxKeys: 10
    }));

    if (!listResult.Contents || listResult.Contents.length === 0) {
      return null;
    }

    const selectedKey = listResult.Contents[0].Key;
    const getResult = await s3Client.send(new GetObjectCommand({
      Bucket: bucketName,
      Key: selectedKey
    }));

    return {
      buffer: Buffer.from(await getResult.Body.transformToByteArray()),
      metadata: {
        source: 'medical_dataset',
        modality: modality,
        severity: 'normal',
        s3Key: selectedKey,
        license: 'CC0/CC-BY (Public Dataset)'
      }
    };
  } catch (error) {
    return null;
  }
}

// ==================== PDF GENERATION ====================

async function generateLabPDF(patient, labData, source, reportDate) {
  return new Promise((resolve, reject) => {
    const doc = new PDFDocument({ margin: 50 });
    const chunks = [];

    doc.on('data', chunk => chunks.push(chunk));
    doc.on('end', () => resolve(Buffer.concat(chunks)));
    doc.on('error', reject);

    // Header
    doc.fontSize(16).font('Helvetica-Bold').text(source, { align: 'center' });
    doc.fontSize(10).font('Helvetica').text('Laboratory Report', { align: 'center' });
    doc.moveDown();

    // Patient Info
    doc.fontSize(10).font('Helvetica-Bold').text('PATIENT INFORMATION');
    doc.font('Helvetica');
    doc.text(`Name: ${patient.last_name}, ${patient.first_name}`);
    doc.text(`DOB: ${patient.patient_dob}`);
    doc.text(`Patient ID: ${patient.patient_id}`);
    doc.text(`Collection Date: ${reportDate}`);
    doc.moveDown();

    // Test Results Header
    doc.font('Helvetica-Bold').text('TEST RESULTS');
    doc.fontSize(12).text(labData.panelName, { underline: true });
    doc.moveDown(0.5);

    // Results Table
    doc.fontSize(9);
    const tableTop = doc.y;
    const col1 = 50, col2 = 250, col3 = 330, col4 = 400, col5 = 480;

    // Table Header
    doc.font('Helvetica-Bold');
    doc.text('Test', col1, tableTop);
    doc.text('Result', col2, tableTop);
    doc.text('Units', col3, tableTop);
    doc.text('Reference', col4, tableTop);
    doc.text('Flag', col5, tableTop);

    doc.moveTo(col1, tableTop + 12).lineTo(520, tableTop + 12).stroke();

    // Table Rows
    doc.font('Helvetica');
    let y = tableTop + 20;

    labData.results.forEach(result => {
      doc.text(result.name, col1, y, { width: 190 });
      doc.text(result.value.toString(), col2, y);
      doc.text(result.unit, col3, y);
      doc.text(result.reference, col4, y);

      if (result.flag) {
        doc.font('Helvetica-Bold').fillColor(result.flag === 'H' ? 'red' : 'blue');
        doc.text(result.flag, col5, y);
        doc.font('Helvetica').fillColor('black');
      }

      y += 15;
    });

    doc.moveDown(2);

    // Footer
    doc.fontSize(8).text('*** End of Report ***', { align: 'center' });
    doc.text(`Report generated: ${new Date().toISOString()}`, { align: 'center' });

    doc.end();
  });
}

// ==================== RADIOLOGY REPORT GENERATION ====================

const radiologyFindings = {
  xray: {
    normal: [
      'No acute cardiopulmonary abnormality.',
      'Clear lungs bilaterally. No pleural effusion or pneumothorax.',
      'Heart size within normal limits. Mediastinal contours are normal.',
      'No acute osseous abnormality.'
    ],
    minor: [
      'Minimal bibasilar atelectasis, likely positional.',
      'Mild cardiomegaly without pulmonary edema.',
      'Small calcified granuloma in the right upper lobe, likely old.',
      'Mild degenerative changes of the thoracic spine.'
    ],
    major: [
      'Right lower lobe consolidation concerning for pneumonia.',
      'Moderate pleural effusion on the left with associated atelectasis.',
      'Enlarged cardiac silhouette with pulmonary vascular congestion.',
      'Suspicious nodule in the right upper lobe measuring 1.5 cm, recommend CT for further evaluation.'
    ],
    critical: [
      'Large right-sided pneumothorax with mediastinal shift, concerning for tension pneumothorax.',
      'Widened mediastinum concerning for aortic dissection, urgent CT recommended.',
      'Diffuse bilateral pulmonary infiltrates consistent with ARDS.',
      'Large pericardial effusion with signs of cardiac tamponade.'
    ]
  },
  ct: {
    normal: [
      'No acute intracranial abnormality.',
      'No evidence of mass, hemorrhage, or infarct.',
      'Ventricles and sulci are normal in size and configuration.',
      'No acute abdominal or pelvic pathology.'
    ],
    minor: [
      'Small hypodense lesion in the liver, too small to characterize, likely benign.',
      'Mild fatty infiltration of the liver.',
      'Small renal cysts bilaterally, no intervention required.',
      'Mild diverticulosis without evidence of diverticulitis.'
    ],
    major: [
      'Enhancing mass in the right kidney measuring 3.2 cm, concerning for renal cell carcinoma.',
      'Multiple hepatic lesions concerning for metastatic disease.',
      'Acute appendicitis with periappendiceal inflammation.',
      'Pulmonary embolism involving the right main pulmonary artery.'
    ],
    critical: [
      'Large intracerebral hemorrhage with significant mass effect and midline shift.',
      'Ruptured abdominal aortic aneurysm with active extravasation.',
      'Massive pulmonary embolism with right heart strain.',
      'Perforated viscus with free air and peritonitis.'
    ]
  },
  mri: {
    normal: [
      'No acute intracranial abnormality on MRI.',
      'Normal brain parenchyma without evidence of mass or infarct.',
      'No abnormal enhancement after contrast administration.',
      'Normal spine alignment with preserved disc heights.'
    ],
    minor: [
      'Few scattered T2 hyperintense foci in the periventricular white matter, nonspecific.',
      'Mild disc bulge at L4-L5 without significant canal stenosis.',
      'Small benign-appearing hemangioma in the vertebral body.',
      'Mild rotator cuff tendinosis without full-thickness tear.'
    ],
    major: [
      'Enhancing mass in the right temporal lobe measuring 2.8 cm, concerning for primary brain tumor.',
      'Large disc herniation at L5-S1 with severe neural foraminal narrowing.',
      'ACL tear with associated bone contusions.',
      'Multiple sclerosis plaques with active enhancement suggesting disease activity.'
    ],
    critical: [
      'Acute brainstem infarct with basilar artery occlusion.',
      'Cauda equina compression requiring emergent surgical evaluation.',
      'Epidural abscess with cord compression.',
      'Pituitary apoplexy with acute hemorrhage.'
    ]
  },
  mra: {
    normal: [
      'Normal intracranial arterial vasculature without aneurysm or stenosis.',
      'Patent carotid and vertebral arteries bilaterally.',
      'No evidence of arteriovenous malformation.',
      'Normal renal arteries without significant stenosis.'
    ],
    minor: [
      'Mild atherosclerotic changes of the carotid bulbs bilaterally.',
      'Small fenestration of the basilar artery, normal variant.',
      'Mild tortuosity of the vertebral arteries.',
      'Minor irregularity of the renal artery, likely atherosclerotic.'
    ],
    major: [
      'Moderate stenosis of the right internal carotid artery (60-70%).',
      'Small aneurysm of the anterior communicating artery measuring 4mm.',
      'Significant stenosis of the left vertebral artery.',
      'Moderate renal artery stenosis with post-stenotic dilatation.'
    ],
    critical: [
      'Large aneurysm of the basilar tip measuring 12mm with irregular contour.',
      'Critical stenosis of the left internal carotid artery (>90%).',
      'Dissection of the right vertebral artery with pseudoaneurysm.',
      'Complete occlusion of the right renal artery.'
    ]
  },
  pet: {
    normal: [
      'No hypermetabolic activity to suggest malignancy.',
      'Physiologic FDG uptake in the brain, heart, and urinary system.',
      'No abnormal lymph node activity.',
      'No evidence of metastatic disease.'
    ],
    minor: [
      'Mildly increased uptake in the right axillary lymph nodes, likely reactive.',
      'Low-grade uptake in a pulmonary nodule, recommend follow-up.',
      'Mild diffuse thyroid uptake, may represent thyroiditis.',
      'Increased colonic uptake, may be physiologic or inflammatory.'
    ],
    major: [
      'Intensely hypermetabolic mass in the right lung concerning for primary malignancy.',
      'Multiple hypermetabolic hepatic lesions consistent with metastatic disease.',
      'FDG-avid mediastinal lymphadenopathy suggesting lymphoma.',
      'Hypermetabolic bone lesions consistent with osseous metastases.'
    ],
    critical: [
      'Widespread metastatic disease involving multiple organ systems.',
      'Massive hypermetabolic tumor with central necrosis.',
      'Extensive lymphomatous involvement of multiple nodal stations.',
      'Diffuse bone marrow involvement suggesting advanced malignancy.'
    ]
  }
};

// Age-appropriate alternative findings for young adults (<45).
// Atherosclerotic findings (stenosis, occlusion) are replaced with
// conditions that actually present in younger patients: FMD, dissection,
// congenital aneurysms, vasculitis, AVM.
const youngAdultFindings = {
  mra: {
    major: [
      'Fibromuscular dysplasia involving the right internal carotid artery with string-of-beads appearance.',
      'Small saccular aneurysm of the anterior communicating artery measuring 4mm, likely congenital.',
      'Spontaneous dissection of the right vertebral artery, consider connective tissue evaluation.',
      'Focal narrowing of the left middle cerebral artery, consider vasculitis workup.'
    ],
    critical: [
      'Acute dissection of the right internal carotid artery with flow-limiting stenosis.',
      'Ruptured berry aneurysm of the anterior communicating artery with subarachnoid hemorrhage.',
      'Bilateral vertebral artery dissection with pseudoaneurysm formation.',
      'Moyamoya pattern with progressive bilateral internal carotid artery stenosis.'
    ]
  },
  ct: {
    critical: [
      'Large intracerebral hemorrhage secondary to arteriovenous malformation rupture.',
      'Ruptured splenic artery aneurysm with active extravasation.',
      'Massive pulmonary embolism with right heart strain.',
      'Perforated viscus with free air and peritonitis.'
    ]
  }
};

async function generateRadiologyReport(type, severity, patient) {
  const findings = radiologyFindings[type] || radiologyFindings.xray;

  // Use age-appropriate findings for young patients (<45) where
  // standard findings would be atherosclerosis-driven and implausible
  const patientAge = calculateAge(patient.patient_dob);
  let impression;
  if (patientAge < 45 && youngAdultFindings[type]?.[severity]) {
    impression = randomElement(youngAdultFindings[type][severity]);
  } else {
    impression = randomElement(findings[severity]);
  }

  // Get real medical image from S3 (sourced from NIH ChestX-ray14, LIDC, etc.)
  const imageData = await getMedicalImage(type, severity);

  return {
    impression: impression,
    imageBuffer: imageData ? imageData.buffer : null,
    imageMetadata: imageData ? imageData.metadata : null
  };
}

async function generateRadiologyPDF(patient, type, impression, source, reportDate) {
  return new Promise((resolve, reject) => {
    const doc = new PDFDocument({ margin: 50 });
    const chunks = [];

    doc.on('data', chunk => chunks.push(chunk));
    doc.on('end', () => resolve(Buffer.concat(chunks)));
    doc.on('error', reject);

    const examNames = {
      xray: 'Chest X-Ray (PA and Lateral)',
      ct: 'CT Scan',
      mri: 'MRI Scan',
      mra: 'MR Angiography',
      pet: 'PET Scan'
    };

    // Header
    doc.fontSize(16).font('Helvetica-Bold').text(source, { align: 'center' });
    doc.fontSize(10).font('Helvetica').text('Radiology Report', { align: 'center' });
    doc.moveDown();

    // Patient Info
    doc.fontSize(10).font('Helvetica-Bold').text('PATIENT INFORMATION');
    doc.font('Helvetica');
    doc.text(`Name: ${patient.last_name}, ${patient.first_name}`);
    doc.text(`DOB: ${patient.patient_dob}`);
    doc.text(`Patient ID: ${patient.patient_id}`);
    doc.moveDown();

    // Exam Info
    doc.font('Helvetica-Bold').text('EXAMINATION');
    doc.font('Helvetica');
    doc.text(`Exam: ${examNames[type] || type.toUpperCase()}`);
    doc.text(`Date: ${reportDate}`);
    doc.moveDown();

    // Clinical History
    doc.font('Helvetica-Bold').text('CLINICAL HISTORY');
    doc.font('Helvetica');
    doc.text('Routine screening / Follow-up examination');
    doc.moveDown();

    // Technique
    doc.font('Helvetica-Bold').text('TECHNIQUE');
    doc.font('Helvetica');
    doc.text(`Standard ${type.toUpperCase()} protocol was performed.`);
    doc.moveDown();

    // Findings
    doc.font('Helvetica-Bold').text('FINDINGS');
    doc.font('Helvetica');
    doc.text(impression, { align: 'justify' });
    doc.moveDown();

    // Impression
    doc.font('Helvetica-Bold').text('IMPRESSION');
    doc.font('Helvetica');
    doc.text(impression, { align: 'justify' });
    doc.moveDown(2);

    // Image source note
    doc.fontSize(8).fillColor('gray');
    doc.text('Note: Associated medical images sourced from NIH ChestX-ray14 dataset (CC0 Public Domain)', { align: 'center' });
    doc.fillColor('black');
    doc.moveDown();

    // Signature
    doc.fontSize(10);
    doc.text('Electronically signed by:');
    doc.text('Dr. ' + ['Smith', 'Johnson', 'Williams', 'Brown', 'Jones'][Math.floor(Math.random() * 5)] + ', MD');
    doc.text('Board Certified Radiologist');
    doc.moveDown();
    doc.fontSize(8).text(`Report generated: ${new Date().toISOString()}`, { align: 'center' });

    doc.end();
  });
}

// ==================== PATHOLOGY REPORT GENERATION ====================

const pathologyFindings = {
  normal: [
    'Benign tissue with no evidence of malignancy.',
    'Normal histological architecture preserved.',
    'No dysplasia or atypia identified.',
    'Benign inflammatory changes only.'
  ],
  minor: [
    'Mild chronic inflammation without specific features.',
    'Hyperplastic polyp, benign.',
    'Low-grade squamous intraepithelial lesion (LSIL).',
    'Mild reactive changes, likely secondary to irritation.'
  ],
  major: [
    'High-grade squamous intraepithelial lesion (HSIL).',
    'Adenomatous polyp with high-grade dysplasia.',
    'Atypical cells present, recommend follow-up biopsy.',
    'Invasive carcinoma, margins need assessment.'
  ],
  critical: [
    'Poorly differentiated carcinoma with lymphovascular invasion.',
    'Melanoma, Breslow depth 4.2mm, Clark level IV.',
    'High-grade sarcoma with extensive necrosis.',
    'Metastatic adenocarcinoma.'
  ]
};

async function generatePathologyPDF(patient, severity, source, reportDate) {
  return new Promise((resolve, reject) => {
    const doc = new PDFDocument({ margin: 50 });
    const chunks = [];

    doc.on('data', chunk => chunks.push(chunk));
    doc.on('end', () => resolve(Buffer.concat(chunks)));
    doc.on('error', reject);

    const commonSpecimens = ['Skin biopsy', 'Colon biopsy', 'Lymph node biopsy'];
    const maleSpecimens = [...commonSpecimens, 'Prostate biopsy'];
    const femaleSpecimens = [...commonSpecimens, 'Breast biopsy', 'Cervical biopsy'];
    const specimenTypes = patient.sex === 'F' ? femaleSpecimens : maleSpecimens;
    const specimen = randomElement(specimenTypes);
    const diagnosis = randomElement(pathologyFindings[severity]);

    // Header
    doc.fontSize(16).font('Helvetica-Bold').text(source, { align: 'center' });
    doc.fontSize(10).font('Helvetica').text('Surgical Pathology Report', { align: 'center' });
    doc.moveDown();

    // Patient Info
    doc.fontSize(10).font('Helvetica-Bold').text('PATIENT INFORMATION');
    doc.font('Helvetica');
    doc.text(`Name: ${patient.last_name}, ${patient.first_name}`);
    doc.text(`DOB: ${patient.patient_dob}`);
    doc.text(`Patient ID: ${patient.patient_id}`);
    doc.moveDown();

    // Specimen Info
    doc.font('Helvetica-Bold').text('SPECIMEN');
    doc.font('Helvetica');
    doc.text(`Type: ${specimen}`);
    doc.text(`Collection Date: ${reportDate}`);
    doc.text(`Accession #: SP-${Date.now()}`);
    doc.moveDown();

    // Gross Description
    doc.font('Helvetica-Bold').text('GROSS DESCRIPTION');
    doc.font('Helvetica');
    doc.text('Received in formalin is a tan-pink soft tissue fragment measuring 0.5 x 0.3 x 0.2 cm. Specimen entirely submitted.');
    doc.moveDown();

    // Microscopic Description
    doc.font('Helvetica-Bold').text('MICROSCOPIC DESCRIPTION');
    doc.font('Helvetica');
    doc.text('Sections examined show tissue with the following findings:');
    doc.text(diagnosis);
    doc.moveDown();

    // Diagnosis
    doc.font('Helvetica-Bold').text('DIAGNOSIS');
    doc.font('Helvetica');
    doc.text(`${specimen}:`);
    doc.text(`- ${diagnosis}`);
    doc.moveDown(2);

    // Signature
    doc.text('Electronically signed by:');
    doc.text('Dr. ' + ['Anderson', 'Martinez', 'Taylor', 'Thomas', 'Garcia'][Math.floor(Math.random() * 5)] + ', MD');
    doc.text('Board Certified Pathologist');
    doc.moveDown();
    doc.fontSize(8).text(`Report generated: ${new Date().toISOString()}`, { align: 'center' });

    doc.end();
  });
}

// ==================== MAIN HANDLER ====================

exports.handler = async (event) => {
  try {
    const patientMasterTable = process.env.PATIENT_MASTER_TABLE;
    const patientResultsTable = process.env.PATIENT_RESULTS_TABLE;
    const bucketName = process.env.REPORTS_BUCKET;

    // Get patient ID from path or pick random
    let patientId = event.pathParameters?.patient_id
      ? parseInt(event.pathParameters.patient_id)
      : null;

    // Get patient
    let patient;
    if (patientId) {
      const result = await docClient.send(new GetCommand({
        TableName: patientMasterTable,
        Key: { patient_id: patientId }
      }));
      patient = result.Item;
    } else {
      // Get random patient
      const scanResult = await docClient.send(new ScanCommand({
        TableName: patientMasterTable
      }));
      if (!scanResult.Items || scanResult.Items.length === 0) {
        return {
          statusCode: 400,
          headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
          body: JSON.stringify({ error: 'No patients found. Please seed the database first.' })
        };
      }
      patient = randomElement(scanResult.Items);
      patientId = patient.patient_id;
    }

    if (!patient) {
      return {
        statusCode: 404,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify({ error: 'Patient not found' })
      };
    }

    // Generate report
    const reportId = uuidv4();
    const reportType = randomElement(REPORT_TYPES);
    const severity = getSeverity();
    const reportDate = new Date().toISOString().split('T')[0];
    const createdAt = new Date().toISOString();

    let source;
    let pdfBuffer;
    let imageBuffer = null;
    let imageMetadata = null;

    if (reportType === 'lab') {
      source = randomElement(LAB_SOURCES);
      const labData = generateLabResults(severity, patient.sex);
      pdfBuffer = await generateLabPDF(patient, labData, source, reportDate);
    } else if (reportType === 'path') {
      source = randomElement(PATHOLOGY_SOURCES);
      pdfBuffer = await generatePathologyPDF(patient, severity, source, reportDate);
    } else {
      // Radiology types: xray, ct, mri, mra, pet
      source = randomElement(RADIOLOGY_SOURCES);
      const radiologyData = await generateRadiologyReport(reportType, severity, patient);
      pdfBuffer = await generateRadiologyPDF(patient, reportType, radiologyData.impression, source, reportDate);
      imageBuffer = radiologyData.imageBuffer;
      imageMetadata = radiologyData.imageMetadata;
    }

    // Upload PDF to S3
    const pdfS3Key = `reports/${patientId}/${reportId}.pdf`;
    await s3Client.send(new PutObjectCommand({
      Bucket: bucketName,
      Key: pdfS3Key,
      Body: pdfBuffer,
      ContentType: 'application/pdf'
    }));

    // Upload image to S3 if exists
    let imageS3Key = null;
    if (imageBuffer) {
      imageS3Key = `images/${patientId}/${reportId}.png`;
      await s3Client.send(new PutObjectCommand({
        Bucket: bucketName,
        Key: imageS3Key,
        Body: imageBuffer,
        ContentType: 'image/png',
        Metadata: imageMetadata ? {
          'source': imageMetadata.source,
          'license': imageMetadata.license,
          'original-key': imageMetadata.s3Key || ''
        } : {}
      }));
    }

    // Create record in DynamoDB
    const reportRecord = {
      patient_id: patientId,
      report_id: reportId,
      report_date: reportDate,
      report_type: reportType,
      reporting_source: source,
      report_pdf_s3_key: pdfS3Key,
      report_image_s3_key: imageS3Key,
      report_final_ind: 'false',
      created_at: createdAt,
      severity: severity,
      // New field: image source metadata
      image_source: imageMetadata ? {
        dataset: imageMetadata.source,
        license: imageMetadata.license,
        modality: imageMetadata.modality
      } : null
    };

    await docClient.send(new PutCommand({
      TableName: patientResultsTable,
      Item: reportRecord
    }));

    return {
      statusCode: 200,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      body: JSON.stringify({
        message: 'Report generated successfully',
        report: reportRecord,
        patient: {
          patient_id: patient.patient_id,
          first_name: patient.first_name,
          last_name: patient.last_name
        },
        imageSource: imageMetadata ? {
          note: 'Real medical image from public dataset',
          dataset: imageMetadata.source,
          license: imageMetadata.license
        } : null
      })
    };
  } catch (error) {
    console.error('Error generating report:', error);
    return {
      statusCode: 500,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      body: JSON.stringify({ error: error.message })
    };
  }
};
