import { openDB } from 'idb';

const DATABASE_NAME = 'paxis-ai';
const DATABASE_VERSION = 1;
const STORE_NAMES = {
  conversations: 'conversations',
  messages: 'messages',
  roadmaps: 'roadmaps',
};

let databasePromise;

function getDatabase() {
  if (!databasePromise) {
    databasePromise = openDB(DATABASE_NAME, DATABASE_VERSION, {
      upgrade(database) {
        if (!database.objectStoreNames.contains(STORE_NAMES.conversations)) {
          const conversations = database.createObjectStore(STORE_NAMES.conversations, { keyPath: 'id' });
          conversations.createIndex('updatedAt', 'updatedAt');
        }
        if (!database.objectStoreNames.contains(STORE_NAMES.messages)) {
          const messages = database.createObjectStore(STORE_NAMES.messages, { keyPath: 'id' });
          messages.createIndex('conversationId', 'conversationId');
          messages.createIndex('createdAt', 'createdAt');
        }
        if (!database.objectStoreNames.contains(STORE_NAMES.roadmaps)) {
          const roadmaps = database.createObjectStore(STORE_NAMES.roadmaps, { keyPath: 'id' });
          roadmaps.createIndex('conversationId', 'conversationId');
        }
      },
    });
  }
  return databasePromise;
}

export async function loadConversations() {
  const database = await getDatabase();
  const [conversations, messages, roadmapRecords] = await Promise.all([
    database.getAll(STORE_NAMES.conversations),
    database.getAll(STORE_NAMES.messages),
    database.getAll(STORE_NAMES.roadmaps),
  ]);
  const roadmapByConversation = Object.fromEntries(
    roadmapRecords.map((record) => [record.conversationId, record.roadmap]),
  );
  return conversations
    .map((conversation) => ({
      ...conversation,
      messages: messages
        .filter((message) => message.conversationId === conversation.id)
        .sort((left, right) => new Date(left.createdAt) - new Date(right.createdAt)),
      roadmap: roadmapByConversation[conversation.id] || null,
    }))
    .sort((left, right) => new Date(right.updatedAt) - new Date(left.updatedAt));
}

export async function saveConversation(conversation) {
  const database = await getDatabase();
  await database.put(STORE_NAMES.conversations, conversation);
}

export async function saveMessage(message) {
  const database = await getDatabase();
  await database.put(STORE_NAMES.messages, message);
}

export async function saveRoadmap(conversationId, roadmap) {
  const database = await getDatabase();
  const record = {
    id: conversationId,
    conversationId,
    roadmap,
    createdAt: new Date().toISOString(),
  };
  await database.put(STORE_NAMES.roadmaps, record);
}

export async function clearConversation(conversationId) {
  const database = await getDatabase();
  const messages = await database.getAll(STORE_NAMES.messages);
  const messageIds = messages
    .filter((message) => message.conversationId === conversationId)
    .map((message) => message.id);
  await Promise.all([
    ...messageIds.map((id) => database.delete(STORE_NAMES.messages, id)),
    database.delete(STORE_NAMES.roadmaps, conversationId),
    database.delete(STORE_NAMES.conversations, conversationId),
  ]);
}

export async function getConversationMessages(conversationId) {
  const database = await getDatabase();
  const messages = await database.getAll(STORE_NAMES.messages);
  return messages
    .filter((message) => message.conversationId === conversationId)
    .sort((left, right) => new Date(left.createdAt) - new Date(right.createdAt));
}

export async function getConversationRoadmap(conversationId) {
  const database = await getDatabase();
  const record = await database.get(STORE_NAMES.roadmaps, conversationId);
  return record?.roadmap || null;
}
