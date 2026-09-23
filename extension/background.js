// extension/background.js
// Open a full review tab; no access to other websites or their contents is needed.
chrome.action.onClicked.addListener(() => {
  chrome.tabs.create({url: chrome.runtime.getURL('review.html')});
});
