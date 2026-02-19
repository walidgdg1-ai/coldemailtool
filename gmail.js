const { google } = require('googleapis');
const db = require('./db');

const BASE_URL = process.env.BASE_URL || 'http://localhost:3000';

function getOAuthClient() {
  return new google.auth.OAuth2(
    process.env.GMAIL_CLIENT_ID,
    process.env.GMAIL_CLIENT_SECRET,
    process.env.GMAIL_REDIRECT_URI || 'http://localhost:3000/auth/callback'
  );
}

function getAuthUrl(state) {
  const oauth2Client = getOAuthClient();
  return oauth2Client.generateAuthUrl({
    access_type: 'offline', prompt: 'consent',
    scope: ['https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/userinfo.email'],
    state,
  });
}

async function exchangeCode(code) {
  const oauth2Client = getOAuthClient();
  const { tokens } = await oauth2Client.getToken(code);
  oauth2Client.setCredentials(tokens);
  const people = google.oauth2({ version: 'v2', auth: oauth2Client });
  const { data } = await people.userinfo.get();
  return { tokens, email: data.email };
}

async function getAuthenticatedClient(inboxId) {
  const inbox = db.getInboxWithTokens(inboxId);
  if (!inbox) throw new Error(`Inbox ${inboxId} not found`);
  const oauth2Client = getOAuthClient();
  oauth2Client.setCredentials({ access_token: inbox.access_token, refresh_token: inbox.refresh_token });
  oauth2Client.on('tokens', (tokens) => { if (tokens.access_token) db.updateInboxTokens(inboxId, tokens.access_token); });
  return { oauth2Client, inbox };
}

function processSpintax(text) {
  if (!text) return text;
  return text.replace(/\{([^{}]+)\}/g, (match, group) => {
    if (match.startsWith('{{')) return match;
    const options = group.split('|');
    if (options.length <= 1) return match;
    return options[Math.floor(Math.random() * options.length)].trim();
  });
}

function personalise(text, lead) {
  if (!text) return '';
  let custom = {};
  try { custom = JSON.parse(lead.custom_data || '{}'); } catch {}
  const vars = { firstName: lead.first_name || '', lastName: lead.last_name || '', fullName: [lead.first_name, lead.last_name].filter(Boolean).join(' '), email: lead.email || '', company: lead.company || '', ...custom };
  let result = processSpintax(text);
  result = result.replace(/\{\{(\w+)\}\}/g, (_, key) => vars[key] !== undefined ? vars[key] : '');
  return result;
}

function makeEmailRaw(to, fromName, fromEmail, subject, htmlBody, options = {}) {
  const { trackingPixel, unsubLink, unsubscribeText, listUnsubHeader } = options;
  const boundary = `----=_Part_${Date.now()}_${Math.random().toString(36).slice(2)}`;
  let finalHtml = htmlBody.replace(/\n/g, '<br>');
  if (unsubLink) { finalHtml += `<br><br><p style="font-size:11px;color:#999;font-family:Arial,sans-serif;"><a href="${unsubLink}" style="color:#999;text-decoration:underline;">${unsubscribeText || 'Unsubscribe'}</a></p>`; }
  if (trackingPixel) { finalHtml += `<img src="${trackingPixel}" width="1" height="1" alt="" style="display:none;width:1px;height:1px;border:0;" />`; }
  const headers = [`From: ${fromName} <${fromEmail}>`, `To: ${to}`, `Subject: ${subject}`, `MIME-Version: 1.0`];
  if (listUnsubHeader) { headers.push(`List-Unsubscribe: <${listUnsubHeader}>`); headers.push(`List-Unsubscribe-Post: List-Unsubscribe=One-Click`); }
  headers.push(`Content-Type: multipart/alternative; boundary="${boundary}"`);
  const plainText = htmlBody.replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '').trim();
  const message = [...headers, '', `--${boundary}`, `Content-Type: text/plain; charset=UTF-8`, `Content-Transfer-Encoding: 7bit`, '', plainText, '', `--${boundary}`, `Content-Type: text/html; charset=UTF-8`, `Content-Transfer-Encoding: 7bit`, '', `<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;">${finalHtml}</body></html>`, '', `--${boundary}--`].join('\r\n');
  return Buffer.from(message).toString('base64url');
}

async function sendEmail({ inboxId, to, subject, body, lead, logId, trackOpens, showUnsubscribe, unsubscribeText }) {
  const { oauth2Client, inbox } = await getAuthenticatedClient(inboxId);
  const gmailApi = google.gmail({ version: 'v1', auth: oauth2Client });
  const personalisedSubject = personalise(subject, lead);
  const personalisedBody = personalise(body, lead);
  const options = {};
  if (trackOpens && logId) options.trackingPixel = `${BASE_URL}/t/${logId}`;
  if (showUnsubscribe) { const u = `${BASE_URL}/unsub/${lead.id}`; options.unsubLink = u; options.listUnsubHeader = u; options.unsubscribeText = unsubscribeText || 'Unsubscribe'; }
  const raw = makeEmailRaw(to, inbox.name, inbox.email, personalisedSubject, personalisedBody, options);
  const res = await gmailApi.users.messages.send({ userId: 'me', requestBody: { raw } });
  return { messageId: res.data.id, subject: personalisedSubject };
}

module.exports = { getAuthUrl, exchangeCode, sendEmail, personalise, processSpintax };
