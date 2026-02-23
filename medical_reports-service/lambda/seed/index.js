const { DynamoDBClient } = require('@aws-sdk/client-dynamodb');
const { DynamoDBDocumentClient, BatchWriteCommand, ScanCommand } = require('@aws-sdk/lib-dynamodb');

const client = new DynamoDBClient({});
const docClient = DynamoDBDocumentClient.from(client);

// Sample data arrays for generating realistic patients
const firstNamesMale = ['James', 'John', 'Robert', 'Michael', 'William', 'David', 'Richard', 'Joseph', 'Thomas', 'Charles', 'Christopher', 'Daniel', 'Matthew', 'Anthony', 'Mark', 'Donald', 'Steven', 'Paul', 'Andrew', 'Joshua'];
const firstNamesFemale = ['Mary', 'Patricia', 'Jennifer', 'Linda', 'Barbara', 'Elizabeth', 'Susan', 'Jessica', 'Sarah', 'Karen', 'Nancy', 'Lisa', 'Betty', 'Margaret', 'Sandra', 'Ashley', 'Dorothy', 'Kimberly', 'Emily', 'Donna'];
const lastNames = ['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis', 'Rodriguez', 'Martinez', 'Hernandez', 'Lopez', 'Gonzalez', 'Wilson', 'Anderson', 'Thomas', 'Taylor', 'Moore', 'Jackson', 'Martin', 'Lee', 'Perez', 'Thompson', 'White', 'Harris', 'Sanchez', 'Clark', 'Ramirez', 'Lewis', 'Robinson'];
const cities = [
  { city: 'New York', state: 'NY', zip: '10001' },
  { city: 'Los Angeles', state: 'CA', zip: '90001' },
  { city: 'Chicago', state: 'IL', zip: '60601' },
  { city: 'Houston', state: 'TX', zip: '77001' },
  { city: 'Phoenix', state: 'AZ', zip: '85001' },
  { city: 'Philadelphia', state: 'PA', zip: '19101' },
  { city: 'San Antonio', state: 'TX', zip: '78201' },
  { city: 'San Diego', state: 'CA', zip: '92101' },
  { city: 'Dallas', state: 'TX', zip: '75201' },
  { city: 'San Jose', state: 'CA', zip: '95101' },
  { city: 'Austin', state: 'TX', zip: '78701' },
  { city: 'Jacksonville', state: 'FL', zip: '32099' },
  { city: 'Fort Worth', state: 'TX', zip: '76101' },
  { city: 'Columbus', state: 'OH', zip: '43085' },
  { city: 'Charlotte', state: 'NC', zip: '28201' },
  { city: 'Seattle', state: 'WA', zip: '98101' },
  { city: 'Denver', state: 'CO', zip: '80201' },
  { city: 'Boston', state: 'MA', zip: '02101' },
  { city: 'Nashville', state: 'TN', zip: '37201' },
  { city: 'Detroit', state: 'MI', zip: '48201' }
];
const streetNames = ['Main St', 'Oak Ave', 'Maple Dr', 'Cedar Ln', 'Pine Rd', 'Elm St', 'Washington Blvd', 'Park Ave', 'Lake Dr', 'River Rd', 'Highland Ave', 'Sunset Blvd', 'Broadway', 'Church St', 'Mill Rd'];

function randomElement(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

function randomPhoneNumber() {
  const areaCode = Math.floor(Math.random() * 900) + 100;
  const prefix = Math.floor(Math.random() * 900) + 100;
  const suffix = Math.floor(Math.random() * 9000) + 1000;
  return `${areaCode}-${prefix}-${suffix}`;
}

function randomDateOfBirth() {
  // Generate DOB between 18 and 85 years ago
  const now = new Date();
  const minAge = 18;
  const maxAge = 85;
  const age = Math.floor(Math.random() * (maxAge - minAge)) + minAge;
  const year = now.getFullYear() - age;
  const month = Math.floor(Math.random() * 12) + 1;
  const day = Math.floor(Math.random() * 28) + 1;
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

function generatePatient(patientId) {
  const sex = Math.random() < 0.5 ? 'M' : 'F';
  const firstName = sex === 'M' ? randomElement(firstNamesMale) : randomElement(firstNamesFemale);
  const lastName = randomElement(lastNames);
  const location = randomElement(cities);
  const streetNumber = Math.floor(Math.random() * 9999) + 1;
  const streetName = randomElement(streetNames);

  return {
    patient_id: patientId,
    patient_dob: randomDateOfBirth(),
    first_name: firstName,
    last_name: lastName,
    sex: sex,
    home_phone: randomPhoneNumber(),
    work_phone: Math.random() < 0.7 ? randomPhoneNumber() : '',
    cell_phone: randomPhoneNumber(),
    address_1: `${streetNumber} ${streetName}`,
    address_2: Math.random() < 0.2 ? `Apt ${Math.floor(Math.random() * 500) + 1}` : '',
    city: location.city,
    state: location.state,
    zipcode: location.zip
  };
}

async function seedPatients() {
  const tableName = process.env.PATIENT_MASTER_TABLE;

  // Check if table already has data
  const scanResult = await docClient.send(new ScanCommand({
    TableName: tableName,
    Limit: 1
  }));

  if (scanResult.Items && scanResult.Items.length > 0) {
    return { message: 'Table already contains data. Skipping seed.', count: 0 };
  }

  // Generate 100 patients
  const patients = [];
  for (let i = 1; i <= 100; i++) {
    patients.push(generatePatient(i));
  }

  // Batch write in groups of 25 (DynamoDB limit)
  let totalWritten = 0;
  for (let i = 0; i < patients.length; i += 25) {
    const batch = patients.slice(i, i + 25);
    const writeRequests = batch.map(patient => ({
      PutRequest: { Item: patient }
    }));

    await docClient.send(new BatchWriteCommand({
      RequestItems: {
        [tableName]: writeRequests
      }
    }));

    totalWritten += batch.length;
  }

  return { message: 'Successfully seeded patients', count: totalWritten };
}

exports.handler = async (event) => {
  try {
    const result = await seedPatients();

    return {
      statusCode: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      },
      body: JSON.stringify(result)
    };
  } catch (error) {
    console.error('Error seeding patients:', error);
    return {
      statusCode: 500,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      },
      body: JSON.stringify({ error: error.message })
    };
  }
};
