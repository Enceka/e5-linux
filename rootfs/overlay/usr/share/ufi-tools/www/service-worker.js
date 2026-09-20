const CACHE_NAME = 'ufi_tools_sw_cache';
const URLS_TO_CACHE = [
  '/',
  '/index.html',
  '/style/style.css',
  '/main.js',
  '/draglist.js',
  '/requests.js',
  '/theme.js',
  '/utils.js',
  '/icons/icon-192.webp',
  '/icons/icon-512.webp'
];

// 检查是否支持ServiceWorker
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js')
      .then(registration => {
        self.addEventListener('install', event => {
          event.waitUntil(
            caches.open(CACHE_NAME).then(cache => {
              return cache.addAll(URLS_TO_CACHE);
            })
          );
        });

        self.addEventListener('fetch', event => {
          event.respondWith(
            caches.match(event.request).then(response => {
              return response || fetch(event.request);
            })
          );
        });
        console.log('ServiceWorker注册成功:', registration);
      })
      .catch(error => {
        console.error('ServiceWorker注册失败:', error);
      });
  });
} else {
  console.warn('当前浏览器不支持ServiceWorker');
}


// window.addEventListener('load', () => {
//   const div = document.createElement('div');
//   const iframe = document.createElement('iframe');
//   iframe.src = 'https://i.kano.ink';
//   iframe.width = "100%"
//   iframe.style.height = "400px"
//   iframe.frameBorder = "0"
//   iframe.allow = "clipboard-write; camera; microphone; fullscreen; autoplay; encrypted-media";
//   iframe.allowFullscreen = true;
//   iframe.style.border = "none";
//   div.style.width = "100%"
//   div.appendChild(iframe);
//   document.querySelector('.container').insertBefore(div, document.querySelector('#collapseBtn_menu'));
// })