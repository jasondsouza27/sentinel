// Appends invented messages so the demo shows auto-scan reacting to new content.
const incoming = [
  ['Prize Office', 'You won a free laptop! Pay the processing fee today at ', 'http://203.0.113.9/claim', 'http://203.0.113.9/claim'],
  ['Maya', 'Running ten minutes late, save me a seat please.'],
  ['IT Helpdesk', 'Your password expires today. Verify now at ', 'https://it-helpdesk.verify-portal.example.com/', 'portal.university.example.edu'],
  // Modern conversational scams: the text model misses these; the community network catches them
  // once other users have reported the campaign (run: python -m sentinel.network demo-seed).
  ['Inspector Verma', 'Hello this is inspector Verma from the cyber crime branch. A parcel in ur name had illegal items. Stay on the video call and dont tell your family.'],
  ['+91 98xxx xxx10', 'hey its me, lost my phone so this is my new number. can u send me 2000 on gpay urgently, will return it tonight'],
  ['Neha (HR)', 'Hi dear, I am Neha from the HR team. We have a part time job, just like YouTube videos and earn 800 to 4000 daily. Interested? Reply yes'],
];
let next = 0;

document.getElementById('incoming').addEventListener('click', () => {
  const [name, text, href, shown] = incoming[next % incoming.length];
  next += 1;
  const article = document.createElement('article');
  article.className = 'msg new';
  const author = document.createElement('b');
  author.textContent = name;
  const body = document.createElement('p');
  body.textContent = text;
  if (href) {
    const link = document.createElement('a');
    link.href = href;
    link.textContent = shown;
    body.append(link);
  }
  const avatar = document.createElement('span');
  avatar.className = 'avatar';
  avatar.setAttribute('aria-hidden', 'true');
  avatar.textContent = /[A-Za-z]/.test(name[0]) ? name[0] : '#';
  const content = document.createElement('div');
  content.append(author, body);
  article.append(avatar, content);
  document.getElementById('feed').append(article);
  article.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
});

// A chat "screenshot" drawn on a canvas: its words exist only as pixels, so only
// the extension's image reading can check them.
function drawChatShot(canvas) {
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.width, height = canvas.height;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  canvas.style.width = `${width}px`;
  const context = canvas.getContext('2d');
  context.scale(ratio, ratio);
  context.fillStyle = '#ece5dd';
  context.fillRect(0, 0, width, height);
  context.fillStyle = '#ffffff';
  context.beginPath();
  context.roundRect(14, 14, width - 60, height - 28, 12);
  context.fill();
  context.fillStyle = '#075e54';
  context.font = '600 15px Helvetica, Arial, sans-serif';
  context.fillText('Boss', 28, 40);
  context.fillStyle = '#111111';
  context.font = '16px Helvetica, Arial, sans-serif';
  ['I am in a meeting. Buy 5 gift cards', 'immediately and send me the codes.', 'Pay with UPI, I will return the money', 'tonight.']
    .forEach((line, index) => context.fillText(line, 28, 66 + index * 22));
}
const chatShot = document.getElementById('chat-shot');
if (chatShot) drawChatShot(chatShot);
