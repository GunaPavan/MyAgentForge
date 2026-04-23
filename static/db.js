// Browser-side project store using IndexedDB.
// All history lives here. Nothing is sent to the server.
// If the user clears their browser data, everything is wiped (by design).

const DB_NAME = "myagentforge";
const DB_VERSION = 1;
const STORE = "projects";

let _dbPromise = null;

function openDb() {
    if (_dbPromise) return _dbPromise;
    _dbPromise = new Promise((resolve, reject) => {
        const req = indexedDB.open(DB_NAME, DB_VERSION);
        req.onupgradeneeded = (e) => {
            const db = e.target.result;
            if (!db.objectStoreNames.contains(STORE)) {
                const store = db.createObjectStore(STORE, { keyPath: "id" });
                store.createIndex("updated_at", "updated_at", { unique: false });
            }
        };
        req.onsuccess = (e) => resolve(e.target.result);
        req.onerror = (e) => reject(e.target.error);
    });
    return _dbPromise;
}

function tx(mode) {
    return openDb().then(db => db.transaction(STORE, mode).objectStore(STORE));
}

function randomId() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

export async function createProject(task) {
    const now = Date.now();
    const project = {
        id: randomId(),
        title: (task || "Untitled").slice(0, 120),
        initial_task: task,
        created_at: now,
        updated_at: now,
        runs: [],
        messages: [],
        files: {},
    };
    const store = await tx("readwrite");
    await new Promise((resolve, reject) => {
        const req = store.add(project);
        req.onsuccess = () => resolve();
        req.onerror = (e) => reject(e.target.error);
    });
    return project;
}

export async function updateProject(project) {
    project.updated_at = Date.now();
    const store = await tx("readwrite");
    return new Promise((resolve, reject) => {
        const req = store.put(project);
        req.onsuccess = () => resolve(project);
        req.onerror = (e) => reject(e.target.error);
    });
}

export async function getProject(id) {
    const store = await tx("readonly");
    return new Promise((resolve, reject) => {
        const req = store.get(id);
        req.onsuccess = (e) => resolve(e.target.result || null);
        req.onerror = (e) => reject(e.target.error);
    });
}

export async function listProjects() {
    const store = await tx("readonly");
    return new Promise((resolve, reject) => {
        const req = store.getAll();
        req.onsuccess = (e) => {
            const all = e.target.result || [];
            all.sort((a, b) => b.updated_at - a.updated_at);
            resolve(all);
        };
        req.onerror = (e) => reject(e.target.error);
    });
}

export async function deleteProject(id) {
    const store = await tx("readwrite");
    return new Promise((resolve, reject) => {
        const req = store.delete(id);
        req.onsuccess = () => resolve(true);
        req.onerror = (e) => reject(e.target.error);
    });
}

export async function clearAll() {
    const store = await tx("readwrite");
    return new Promise((resolve, reject) => {
        const req = store.clear();
        req.onsuccess = () => resolve(true);
        req.onerror = (e) => reject(e.target.error);
    });
}
