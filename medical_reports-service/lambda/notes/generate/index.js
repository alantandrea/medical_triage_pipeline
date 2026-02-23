/**
 * Generate Sample Patient Note Lambda
 *
 * Creates realistic sample patient notes for testing the AI pipeline.
 * Simulates SMS messages patients might send to their doctor's office.
 *
 * @endpoint POST /notes/generate
 * @endpoint POST /notes/generate/{patient_id}
 */

const { DynamoDBClient } = require('@aws-sdk/client-dynamodb');
const { DynamoDBDocumentClient, PutCommand, ScanCommand, GetCommand } = require('@aws-sdk/lib-dynamodb');
const { v4: uuidv4 } = require('uuid');

const dynamoClient = new DynamoDBClient({});
const docClient = DynamoDBDocumentClient.from(dynamoClient);

// Sample patient note templates with varying severity
const NOTE_TEMPLATES = {
  normal: [
    {
      text: "Just checking in, feeling good today. My sugar this morning was {glucose} and I took my meds.",
      vitals: { blood_sugar_level: [85, 110] },
      symptoms: [],
      urgency: []
    },
    {
      text: "Wanted to let you know my blood pressure has been stable. Checked it today: {systolic}/{diastolic}. Weight is {weight} lbs.",
      vitals: { systolic: [115, 125], diastolic: [70, 80], weight: [150, 180] },
      symptoms: [],
      urgency: []
    },
    {
      text: "My A1C home test showed {a1c}%. Feeling pretty good overall, no complaints.",
      vitals: { hemoglobin_a1c: [5.0, 5.6] },
      symptoms: [],
      urgency: []
    },
    {
      text: "Temperature normal at {temp}. Just wanted to update you that I'm recovering well from my cold.",
      vitals: { temperature: [97.5, 98.6] },
      symptoms: [],
      urgency: []
    }
  ],
  minor: [
    {
      text: "Been having some headaches this week. Temp is {temp}. Pain about {pain} out of 10. Taking tylenol which helps.",
      vitals: { temperature: [98.5, 99.5], pain_scale: [3, 4] },
      symptoms: ["headaches"],
      urgency: []
    },
    {
      text: "My sugar has been running a bit high lately. This morning it was {glucose}. Been stressed at work.",
      vitals: { blood_sugar_level: [140, 170] },
      symptoms: ["elevated blood sugar"],
      urgency: []
    },
    {
      text: "Feeling a little tired and achy. Temp {temp}. Oxygen is {sp02}%. Think I might be coming down with something.",
      vitals: { temperature: [99.0, 100.0], sp02: [95, 97] },
      symptoms: ["fatigue", "body aches"],
      urgency: []
    },
    {
      text: "Blood pressure was {systolic}/{diastolic} today, a bit higher than usual. Have been eating salty food this week.",
      vitals: { systolic: [135, 145], diastolic: [85, 92] },
      symptoms: [],
      urgency: []
    }
  ],
  major: [
    {
      text: "Not feeling well at all. Temp is {temp} and I have pain in my stomach area, about {pain}/10. Been going on for 2 days now.",
      vitals: { temperature: [100.5, 102.0], pain_scale: [5, 7] },
      symptoms: ["abdominal pain", "fever"],
      urgency: ["persistent abdominal pain"]
    },
    {
      text: "My sugar was {glucose} this morning which is really high for me. Feeling dizzy and nauseous. Should I be worried?",
      vitals: { blood_sugar_level: [250, 350] },
      symptoms: ["dizziness", "nausea", "hyperglycemia"],
      urgency: ["very high blood sugar"]
    },
    {
      text: "Having trouble catching my breath today. Oxygen is showing {sp02}% on my home monitor. BP {systolic}/{diastolic}.",
      vitals: { sp02: [90, 93], systolic: [145, 160], diastolic: [90, 100] },
      symptoms: ["shortness of breath"],
      urgency: ["difficulty breathing"]
    },
    {
      text: "Severe headache for 3 days now, pain is {pain}/10. Temp {temp}. Light is bothering my eyes. Very worried.",
      vitals: { temperature: [100.0, 101.5], pain_scale: [7, 8] },
      symptoms: ["severe headache", "photophobia"],
      urgency: ["persistent severe headache"]
    }
  ],
  critical: [
    {
      text: "Having chest pain and trouble breathing. Pain is {pain}/10. Heart racing. Very scared. Should I call 911?",
      vitals: { pain_scale: [8, 10], heart_rate: [110, 140] },
      symptoms: ["chest pain", "shortness of breath", "palpitations"],
      urgency: ["chest pain", "difficulty breathing", "cardiac symptoms"]
    },
    {
      text: "Mom is confused and not making sense. Temp is {temp}. She's been sick for a few days. Very weak. Please help.",
      vitals: { temperature: [102.5, 104.0] },
      symptoms: ["confusion", "altered mental status", "high fever", "weakness"],
      urgency: ["confusion", "altered mental status", "high fever"]
    },
    {
      text: "Sugar was {glucose} and I feel terrible. Sweating, shaking, can barely stand. Took my insulin already.",
      vitals: { blood_sugar_level: [35, 55] },
      symptoms: ["hypoglycemia", "diaphoresis", "tremors", "weakness"],
      urgency: ["severe hypoglycemia", "altered consciousness"]
    },
    {
      text: "Oxygen dropped to {sp02}% and I can't breathe lying down. Coughing up pink stuff. Very scared.",
      vitals: { sp02: [82, 88] },
      symptoms: ["severe shortness of breath", "orthopnea", "hemoptysis"],
      urgency: ["severe hypoxia", "respiratory distress", "possible pulmonary edema"]
    },
    {
      text: "Worst headache of my life came on suddenly. {pain}/10 pain. Feel like I'm going to pass out. Neck stiff.",
      vitals: { pain_scale: [10, 10] },
      symptoms: ["thunderclap headache", "neck stiffness", "near syncope"],
      urgency: ["thunderclap headache", "possible SAH", "meningeal signs"]
    }
  ]
};

// Severity distribution: 40% normal, 25% minor, 20% major, 15% critical
const SEVERITY_WEIGHTS = {
  normal: 40,
  minor: 25,
  major: 20,
  critical: 15
};

/**
 * Select severity based on weighted distribution.
 */
function selectSeverity() {
  const total = Object.values(SEVERITY_WEIGHTS).reduce((a, b) => a + b, 0);
  let random = Math.random() * total;

  for (const [severity, weight] of Object.entries(SEVERITY_WEIGHTS)) {
    random -= weight;
    if (random <= 0) {
      return severity;
    }
  }
  return 'normal';
}

/**
 * Generate a random value within a range.
 */
function randomInRange(range, decimals = 0) {
  const [min, max] = range;
  const value = min + Math.random() * (max - min);
  return decimals > 0 ? Math.round(value * Math.pow(10, decimals)) / Math.pow(10, decimals) : Math.round(value);
}

/**
 * Generate a sample note from a template.
 */
function generateNoteFromTemplate(template) {
  let text = template.text;
  const vitals = {};

  // Replace placeholders with random values
  if (template.vitals.blood_sugar_level) {
    vitals.blood_sugar_level = randomInRange(template.vitals.blood_sugar_level);
    text = text.replace('{glucose}', vitals.blood_sugar_level);
  }
  if (template.vitals.temperature) {
    vitals.temperature = randomInRange(template.vitals.temperature, 1);
    text = text.replace('{temp}', vitals.temperature);
  }
  if (template.vitals.pain_scale) {
    vitals.pain_scale = randomInRange(template.vitals.pain_scale);
    text = text.replace('{pain}', vitals.pain_scale);
  }
  if (template.vitals.systolic) {
    vitals.systolic = randomInRange(template.vitals.systolic);
    text = text.replace('{systolic}', vitals.systolic);
  }
  if (template.vitals.diastolic) {
    vitals.diastolic = randomInRange(template.vitals.diastolic);
    text = text.replace('{diastolic}', vitals.diastolic);
  }
  if (template.vitals.sp02) {
    vitals.sp02 = randomInRange(template.vitals.sp02);
    text = text.replace('{sp02}', vitals.sp02);
  }
  if (template.vitals.weight) {
    vitals.weight = randomInRange(template.vitals.weight);
    text = text.replace('{weight}', vitals.weight);
  }
  if (template.vitals.hemoglobin_a1c) {
    vitals.hemoglobin_a1c = randomInRange(template.vitals.hemoglobin_a1c, 1);
    text = text.replace('{a1c}', vitals.hemoglobin_a1c);
  }
  if (template.vitals.heart_rate) {
    vitals.heart_rate = randomInRange(template.vitals.heart_rate);
    text = text.replace('{hr}', vitals.heart_rate);
  }

  return {
    text,
    vitals,
    symptoms: template.symptoms,
    urgency: template.urgency
  };
}

/**
 * Get a random patient from the database.
 */
async function getRandomPatient(specificPatientId = null) {
  if (specificPatientId) {
    // Direct key lookup — patient_id is the partition key
    const result = await docClient.send(new GetCommand({
      TableName: process.env.PATIENT_MASTER_TABLE,
      Key: { patient_id: parseInt(specificPatientId) }
    }));
    return result.Item;
  }

  // Get random patient
  const result = await docClient.send(new ScanCommand({
    TableName: process.env.PATIENT_MASTER_TABLE,
    Limit: 100
  }));

  if (!result.Items || result.Items.length === 0) {
    return null;
  }

  const randomIndex = Math.floor(Math.random() * result.Items.length);
  return result.Items[randomIndex];
}

/**
 * Main Lambda handler.
 */
exports.handler = async (event) => {
  console.log('Generate note request:', JSON.stringify(event, null, 2));

  try {
    const specificPatientId = event.pathParameters?.patient_id;

    // Get a patient
    const patient = await getRandomPatient(specificPatientId);

    if (!patient) {
      return {
        statusCode: 404,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({
          error: specificPatientId
            ? `Patient ${specificPatientId} not found`
            : 'No patients found. Run /seed first.'
        })
      };
    }

    // Select severity and template
    const severity = selectSeverity();
    const templates = NOTE_TEMPLATES[severity];
    const template = templates[Math.floor(Math.random() * templates.length)];

    // Generate note content
    const generated = generateNoteFromTemplate(template);

    // Create note record
    const noteId = uuidv4();
    const now = new Date().toISOString();

    const noteRecord = {
      // Keys
      patient_id: patient.patient_id,
      note_id: noteId,

      // Timestamps
      note_date: now,
      created_at: now,

      // Source info (simulated)
      from_phone: patient.cell_phone || '555-000-0000',
      patient_name: `${patient.first_name} ${patient.last_name}`,

      // Processing status
      processed: 'false',

      // Content
      note_text: generated.text,

      // Pre-extracted vitals
      temperature: generated.vitals.temperature || null,
      pain_scale: generated.vitals.pain_scale || null,
      sp02: generated.vitals.sp02 || null,
      systolic: generated.vitals.systolic || null,
      diastolic: generated.vitals.diastolic || null,
      weight: generated.vitals.weight || null,
      blood_sugar_level: generated.vitals.blood_sugar_level || null,
      heart_rate: generated.vitals.heart_rate || null,
      hemoglobin_a1c: generated.vitals.hemoglobin_a1c || null,

      // Symptoms and urgency
      symptoms: generated.symptoms,
      urgency_indicators: generated.urgency,
      has_urgency: generated.urgency.length > 0,

      // Metadata
      severity: severity,  // For testing/validation
      extraction_method: 'template-generated',
      extraction_confidence: 'high',
      values_extracted: Object.keys(generated.vitals).length
    };

    // Save to DynamoDB
    await docClient.send(new PutCommand({
      TableName: process.env.PATIENT_NOTES_TABLE,
      Item: noteRecord
    }));

    console.log(`Generated ${severity} note ${noteId} for patient ${patient.patient_id}`);

    return {
      statusCode: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      },
      body: JSON.stringify({
        message: 'Patient note generated successfully',
        note: {
          note_id: noteId,
          patient_id: patient.patient_id,
          patient_name: noteRecord.patient_name,
          severity: severity,
          note_text: generated.text,
          vitals: generated.vitals,
          symptoms: generated.symptoms,
          urgency_indicators: generated.urgency,
          has_urgency: noteRecord.has_urgency
        }
      })
    };

  } catch (error) {
    console.error('Error generating note:', error);
    return {
      statusCode: 500,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      },
      body: JSON.stringify({
        error: 'Failed to generate note',
        message: error.message
      })
    };
  }
};
