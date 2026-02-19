const crypto = require('crypto');

const ALGO = 'aes-256-cbc';
const KEY = process.env.ENCRYPTION_KEY
  ? Buffer.from(process.env.ENCRYPTION_KEY, 'hex')
  : null;

if (!KEY) {
  console.warn('⚠️  ENCRYPTION_KEY not set in .env!');
  console.warn('   Generate one with: openssl rand -hex 32');
  console.warn('   Tokens will be stored in plain text until set.\n');
}

function encrypt(text) {
  if (!KEY || !text) return text;
  const iv = crypto.randomBytes(16);
  const cipher = crypto.createCipheriv(ALGO, KEY, iv);
  let encrypted = cipher.update(text, 'utf8', 'hex');
  encrypted += cipher.final('hex');
  return iv.toString('hex') + ':' + encrypted;
}

function decrypt(text) {
  if (!KEY || !text || !text.includes(':')) return text;
  try {
    const colonIndex = text.indexOf(':');
    const ivHex = text.substring(0, colonIndex);
    const encryptedHex = text.substring(colonIndex + 1);
    if (ivHex.length !== 32) return text;
    const decipher = crypto.createDecipheriv(ALGO, KEY, Buffer.from(ivHex, 'hex'));
    let decrypted = decipher.update(encryptedHex, 'hex', 'utf8');
    decrypted += decipher.final('utf8');
    return decrypted;
  } catch {
    return text;
  }
}

module.exports = { encrypt, decrypt };
