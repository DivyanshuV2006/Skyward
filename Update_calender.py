import datetime
import requests
import re
from bs4 import BeautifulSoup
import json
from notion_client import Client
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options

# Login to Skyward and get session
def login_to_skyward():
    session = requests.Session()
    payload = {
        'login': username,
        'password': password
    }
    response = session.post(login_url, data=payload)
    if response.status_code == 200 and 'Calendar' in response.text:
        print("Login successful.")
        return session
    else:
        raise Exception("Failed to log in to Skyward. Check your credentials.")

# Scrape Skyward calendar
def scrape_calendar_with_selenium(username, password, calendar_url, login_url):

    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Enable headless mode
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
    
    driver.get(login_url)

    try:
        username_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@name='UserName']"))
        )
    except Exception as e:
        print("Error finding username field:", e)
        driver.quit()
        return []

    try:
        password_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@name='Password']"))
        )
    except Exception as e:
        print("Error finding password field:", e)
        driver.quit()
        return []

    username_field.send_keys(username)
    password_field.send_keys(password)
    password_field.send_keys(Keys.RETURN)
    
    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.ID, "generalCalendar"))
        )
    except Exception as e:
        print("Error loading the calendar page:", e)
        driver.quit()
        return []

    driver.get(calendar_url)

    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CLASS_NAME, "fc-event-title"))
        )
    except Exception as e:
        print("Error loading calendar events:", e)
        driver.quit()
        return []

    page_source = driver.page_source
    soup = BeautifulSoup(page_source, 'html.parser')
    
    calendar_data = soup.find('div', id='generalCalendar')['data-events']
    events_json = json.loads(calendar_data)
    
    events = []
    
    for event in events_json:
        event_data = {
            'title': event.get('title', 'No Title'),
            'description': event.get('Description', 'No Description'),
            'date': event.get('DueDate', 'No Date')
        }
        events.append(event_data)
    
    driver.quit()

    return events

# Add events to Notion
def add_to_notion(events):
    notion = Client(auth=notion_token)
    
    for event in events:
        # Check if the description exceeds 2000 characters and truncate if necessary
        description = event['description']
        if len(description) > 2000:
            description = description[:2000]  # Truncate to 2000 characters
        
        # Query the Notion database to check if the event already exists
        existing_pages = notion.databases.query(
            database_id=notion_database_id,
            filter={
                "property": "Name",
                "title": {
                    "equals": event['title']
                }
            }
        )
        
        # Skip adding the event if an existing page with the same title is found
        if existing_pages['results']:
            print(f"Event '{event['title']}' already exists in Notion. Skipping.")
            continue
        
        # Create a new page in Notion for the event
        notion.pages.create(
            parent={"database_id": notion_database_id},
            properties={
                "Name": {"title": [{"text": {"content": event['title']}}]},
                "Date": {"date": {"start": event['date']}},
                "Description": {"rich_text": [{"text": {"content": description}}]}
            }
        )
    
    print(f"Finished processing events.")

#Clean up the descriptions
def clean_description(text):
    cleaned_text = re.sub(r'[\n\xa0]+', ' ', text)
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
    return cleaned_text

# Convert dates to ISO 8601 format
def convert_to_iso(date_str):
    try:
        clean_date_str = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_str)
        date_obj = datetime.datetime.strptime(clean_date_str, '%B %d, %Y')
        return date_obj.strftime('%Y-%m-%d')
    except ValueError:
        return date_str


# Skyward login credentials
username = 'Username'
password = 'Password'
login_url = 'https://skyward.iscorp.com/LakeTravisTXStuSTS/Session/Signin?area=Calendar&controller=Calendar&action=StudentAccess&tab=General'
calendar_url = 'CalenderUrl'

# Notion token and page ID
notion_token = 'Notion Token'
notion_database_id = 'DataBase ID'



# Main function
def main():
    try:
        events = scrape_calendar_with_selenium(username, password, calendar_url, login_url)
        for event in events:
            event['description'] = clean_description(event['description'])
            event['date'] = convert_to_iso(event['date'])

        print(events)
        if events:
            add_to_notion(events)
        else:
            print("No events found on the calendar.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
