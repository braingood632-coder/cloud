// تهيئة Firebase للموقع. الإعدادات تأتي من /config.js (متغيرات البيئة في السيرفر).
import { initializeApp } from "https://www.gstatic.com/firebasejs/13.4.0/firebase-app.js";
import {
  getAuth, connectAuthEmulator, onAuthStateChanged, signInWithEmailAndPassword,
  createUserWithEmailAndPassword, sendPasswordResetEmail, sendEmailVerification,
  updateProfile, signOut, setPersistence, browserLocalPersistence,
} from "https://www.gstatic.com/firebasejs/13.4.0/firebase-auth.js";
import {
  getFirestore, connectFirestoreEmulator, doc, getDoc, setDoc, updateDoc, deleteDoc, addDoc,
  collection, query, where, onSnapshot, serverTimestamp,
} from "https://www.gstatic.com/firebasejs/13.4.0/firebase-firestore.js";

export const CFG = window.CLOUD_CONFIG || { firebase: {}, emulators: {}, plans: {} };

const usingEmulators = Boolean(CFG.emulators && (CFG.emulators.auth || CFG.emulators.firestore));
export const configured = Boolean(CFG.firebase && CFG.firebase.projectId && (CFG.firebase.apiKey || usingEmulators));

const firebaseConfig = { ...CFG.firebase };
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
  sendEmailVerification, updateProfile, signOut,
  doc, getDoc, setDoc, updateDoc, deleteDoc, addDoc, collection, query, where, onSnapshot, serverTimestamp,
};
