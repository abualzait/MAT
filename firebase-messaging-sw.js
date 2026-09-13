// Service Worker for MAT Application Background & Lock Screen Notifications
importScripts('https://www.gstatic.com/firebasejs/9.22.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/9.22.0/firebase-messaging-compat.js');

// Initialize Firebase with MAT App credentials
firebase.initializeApp({
  projectId: "moi-mat-app",
  messagingSenderId: "111636101983678127810"
});

const messaging = firebase.messaging();

// Handle Push Notifications when app is in background or phone is LOCKED
messaging.onBackgroundMessage((payload) => {
  console.log('[firebase-messaging-sw.js] Background message received:', payload);

  const title = (payload.notification && payload.notification.title) ? payload.notification.title : 'تنبيه جديد - نظام MAT';
  const body = (payload.notification && payload.notification.body) ? payload.notification.body : 'لديك رسالة جديدة في النظام';

  const notificationOptions = {
    body: body,
    icon: '/amman_logo.png',
    badge: '/amman_logo.png',
    vibrate: [200, 100, 200, 100, 200],
    requireInteraction: true,
    tag: (payload.data && payload.data.type) ? payload.data.type : 'mat-notification',
    data: {
      url: (payload.data && payload.data.url) ? payload.data.url : '/complaints/app.html'
    }
  };

  self.registration.showNotification(title, notificationOptions);
});

// Handle clicking on lock screen notification
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const targetUrl = (event.notification.data && event.notification.data.url) 
    ? event.notification.data.url 
    : '/complaints/app.html';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      // If tab is already open, focus it
      for (let client of windowClients) {
        if (client.url.includes('/complaints/') && 'focus' in client) {
          return client.focus();
        }
      }
      // Otherwise open new window
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});
