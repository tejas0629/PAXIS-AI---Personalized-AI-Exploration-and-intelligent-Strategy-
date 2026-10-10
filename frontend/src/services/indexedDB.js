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
  const roadmapByConversation = new Map(
    roadmapRecords
      .filter((record) => record && typeof record.conversationId === 'string')
      .map((record) => [record.conversationId, record]),
  );
  return conversations
    .filter((conversation) => conversation && typeof conversation.id === 'string')
    .map((conversation) => {
      const conversationMessages = messages
        .filter((message) => message && message.conversationId === conversation.id && typeof message.id === 'string')
        .sort((left, right) => new Date(left.createdAt) - new Date(right.createdAt));
      const firstUserMessage = conversationMessages.find((message) => message.role === 'user')?.content;
      const inferredTitle = typeof firstUserMessage === 'string'
        ? (firstUserMessage.replace(/\s+/g, ' ').trim().slice(0, 39) || 'New chat')
        : 'New chat';
      return {
        ...conversation,
        messages: conversationMessages,
        roadmap: roadmapByConversation.get(conversation.id)?.roadmap || null,
        completedItems: roadmapByConversation.get(conversation.id)?.completedItems || [],
        createdAt: conversation.createdAt || conversation.updatedAt || new Date().toISOString(),
        updatedAt: conversation.updatedAt || conversation.createdAt || new Date().toISOString(),
        title: conversation.title || inferredTitle,
        manualTitle: conversation.manualTitle || false,
      };
    })
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
  const existing = await database.get(STORE_NAMES.roadmaps, conversationId);
  const record = {
    id: conversationId,
    conversationId,
    roadmap,
    completedItems: existing?.completedItems || [],
    createdAt: new Date().toISOString(),
  };
  await database.put(STORE_NAMES.roadmaps, record);
}

export async function saveRoadmapProgress(conversationId, completedItems) {
  const database = await getDatabase();
  const existing = await database.get(STORE_NAMES.roadmaps, conversationId);
  if (!existing) return;
  await database.put(STORE_NAMES.roadmaps, {
    ...existing,
    completedItems,
    updatedAt: new Date().toISOString(),
  });
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
  ]);
}

export async function deleteConversation(conversationId) {
  const database = await getDatabase();
  const messages = await database.getAll(STORE_NAMES.messages);
  const messageIds = messages
    .filter((message) => message?.conversationId === conversationId)
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
