// تهيئة Firebase للموقع. الإعدادات تأتي من /config.js (متغيرات البيئة في السيرفر).
import { initializeApp } from "https://www.gstatic.com/firebasejs/13.4.0/firebase-app.js";
import {
  getAuth, connectAuthEmulator, onAuthStateChanged, signInWithEmailAndPassword, reload,
  createUserWithEmailAndPassword, sendPasswordResetEmail, sendEmailVerification,
  updateProfile, signOut, setPersistence, browserLocalPersistence,
} from "https://www.gstatic.com/firebasejs/13.4.0/firebase-auth.js";
import {
  getFirestore, connectFirestoreEmulator, doc, getDoc, setDoc, updateDoc, deleteDoc, addDoc,
  collection, query, where, onSnapshot, serverTimestamp,
} from "https://www.gstatic.com/firebasejs/13.4.0/firebase-firestore.js";

export const CFG = window.CLOUD_CONFIG || { firebase: {}, emulators: {}, plans: {} };

const usingEmulators = Boolean(CFG.emulators && (CFG.emulators.auth || CFG.emulators.firestore));

// على Firebase Hosting تُجلب إعدادات المشروع تلقائياً (لا حاجة لنسخ apiKey يدوياً)
let firebaseConfig = { ...(CFG.firebase || {}) };
if (!firebaseConfig.apiKey && !usingEmulators) {
  try {
    const res = await fetch("/__/firebase/init.json");
    if (res.ok) firebaseConfig = { ...(await res.json()), ...firebaseConfig };
  } catch (e) { /* يظهر تنبيه "غير مضبوط" */ }
}
export const configured = Boolean(firebaseConfig.projectId && (firebaseConfig.apiKey || usingEmulators));

if (!firebaseConfig.apiKey && usingEmulators) firebaseConfig.apiKey = "demo-key";

export const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
auth.languageCode = "ar";
export const db = getFirestore(app);

if (CFG.emulators?.auth) connectAuthEmulator(auth, "http://" + CFG.emulators.auth, { disableWarnings: true });
if (CFG.emulators?.firestore) {
  const [host, port] = CFG.emulators.firestore.split(":");
  connectFirestoreEmulator(db, host, Number(port));
}
setPersistence(auth, browserLocalPersistence).catch(() => {});

export {
  onAuthStateChanged, signInWithEmailAndPassword, createUserWithEmailAndPassword, sendPasswordResetEmail,
  sendEmailVerification, updateProfile, signOut, reload,
  doc, getDoc, setDoc, updateDoc, deleteDoc, addDoc, collection, query, where, onSnapshot, serverTimestamp,
};
