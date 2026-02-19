/**
 * Standalone scheduler worker process.
 * Runs the cron scheduler WITHOUT starting the Express web server.
 * Both web and worker MUST point to the same DB_PATH.
 */

require('dotenv').config();
console.log('[Worker] Cold Email Scheduler — standalone mode');
console.log(`[Worker] DB: ${process.env.DB_PATH || './data.db'}\n`);
require('./db');
const scheduler = require('./scheduler');
scheduler.start();
process.on('SIGTERM', () => { console.log('[Worker] SIGTERM'); process.exit(0); });
process.on('SIGINT', () => { console.log('[Worker] SIGINT'); process.exit(0); });
