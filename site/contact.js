// This page opens an email client only after an explicit choice.
// Include useful prompts in the draft so a first enquiry gives bookings
// enough information to respond, without assuming callers have a phone.
const mailLink = document.getElementById('enquiry-email-link');
const mailSubject = 'Goodwood Institute venue enquiry';
const mailBody = [
  'Hello Goodwood Institute team,',
  '',
  'Space(s) of interest (or not sure yet): ',
  'Preferred date(s) and times (if known): ',
  'What I am planning / approximate attendance: ',
  'Any other questions or requirements: ',
  '',
  'My name: ',
  'How best to reply: ',
  '',
].join('\n');
mailLink.href = 'mailto:bookings@goodwoodinstitute.asn.au'
  + '?subject=' + encodeURIComponent(mailSubject)
  + '&body=' + encodeURIComponent(mailBody);

const contactForm = document.getElementById('contact-form');
const button = contactForm.querySelector('button[type="submit"]');
const status = document.getElementById('contact-status');

contactForm.addEventListener('submit', async event => {
  event.preventDefault();
  button.disabled = true;
  status.textContent = 'Sending your enquiry…';
  try {
    const response = await fetch(contactForm.action, {
      method: 'POST',
      body: new FormData(contactForm),
      headers: { Accept: 'application/json' },
      credentials: 'same-origin'
    });
    if (!response.ok) {
      const details = await response.json().catch(() => ({}));
      throw new Error(details.error || 'We could not send your enquiry. Please try again.');
    }
    contactForm.reset();
    status.textContent = 'Thank you. Your enquiry has been received. Our bookings team will reply by email.';
    status.setAttribute('tabindex', '-1');
    status.focus();
  } catch (error) {
    status.textContent = error.message + ' You can also email bookings@goodwoodinstitute.asn.au.';
  } finally {
    button.disabled = false;
  }
});
