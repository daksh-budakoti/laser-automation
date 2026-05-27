import imaplib
import email
import os
from email.header import decode_header

EMAIL = "dakshsharma20004@gmail.com"
APP_PASSWORD = "flkeexqbhjslpjxb"

SAVE_DIR = "downloads"

def fetch_latest_xml():

    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR)

    mail = imaplib.IMAP4_SSL("imap.gmail.com")

    mail.login(EMAIL, APP_PASSWORD)

    mail.select("inbox")

    # Search unread emails
    status, messages = mail.search(None, 'UNSEEN')

    email_ids = messages[0].split()

    if not email_ids:
        print("No new email found")
        return None

    # newest first
    for email_id in reversed(email_ids):

        status, msg_data = mail.fetch(
            email_id,
            "(RFC822)"
        )

        msg = email.message_from_bytes(
            msg_data[0][1]
        )

        for part in msg.walk():

            filename = part.get_filename()

            if filename and filename.lower().endswith(".xml"):

                decoded_name, encoding = decode_header(filename)[0]

                if isinstance(decoded_name, bytes):
                    filename = decoded_name.decode(
                        encoding or "utf-8"
                    )

                filepath = os.path.join(
                    SAVE_DIR,
                    filename
                )

                with open(filepath, "wb") as f:
                    f.write(
                        part.get_payload(
                            decode=True
                        )
                    )

                print(
                    f"Downloaded: {filepath}"
                )

                mail.logout()

                return filepath

    mail.logout()

    return None


if __name__ == "__main__":
    fetch_latest_xml()