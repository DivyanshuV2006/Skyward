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
from selenium.webdriver.chrome.options import Options  # Import Options for headless mode
from dotenv import load_dotenv
import os
from tqdm import tqdm

# Load environment variables from the .env file
load_dotenv()

# Read credentials and other settings from environment variables
username = os.getenv('SKYWARD_USERNAME')
password = os.getenv('SKYWARD_PASSWORD')
login_url = os.getenv('LOGIN_URL')
calendar_url = os.getenv('CALENDAR_URL')
notion_token = os.getenv('NOTION_TOKEN')
notion_database_id = os.getenv('NOTION_DATABASE_ID')

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
    # Set up Chrome options for headless mode
    options = Options()
    options.add_argument("--headless")  # Enable headless mode
    options.add_argument("--disable-gpu")  # Disable GPU (optional, for better performance)
    options.add_argument("--no-sandbox")  # For running in Docker environments (optional)

    # Initialize the Chrome WebDriver with the specified options
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
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
            'date': event.get('DueDate', 'No Date'),
            'course': event.get('Course', 'No Course')  # Assuming the course info is part of the event
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
        
        # Query the Notion database to check if the event already exists based on both title and description
        existing_pages = notion.databases.query(
            database_id=notion_database_id,
            filter={
                "and": [
                    {
                        "property": "Name",
                        "title": {
                            "equals": event['title']
                        }
                    },
                    {
                        "property": "Description",
                        "rich_text": {
                            "equals": event['description']
                        }
                    }
                ]
            }
        )
        
        # Skip adding the event if an existing page with the same title and description is found
        if existing_pages['results']:
            #print(f"Event '{event['title']}' with the same description already exists in Notion. Skipping.")
            continue
        
        # Print the message indicating the event is being added
        #print(f"Adding event '{event['title']}'")
        
        # Create a new page in Notion for the event
        event_page = notion.pages.create(
            parent={"database_id": notion_database_id},
            properties={
                "Name": {"title": [{"text": {"content": event['title']}}]},
                "Date": {"date": {"start": event['date']}},
                "Description": {"rich_text": [{"text": {"content": description}}]},
            }
        )

        # Now, if the 'Course' property exists, add it
        try:
            # Retrieve the database schema
            database_schema = notion.databases.retrieve(database_id=notion_database_id)
            properties = database_schema.get('properties', {})
            course_property_exists = False

            # Check if 'Course' property exists
            if isinstance(properties, dict):
                course_property_exists = 'Course' in properties
            
            if course_property_exists:
                # Assuming event_page_id is the ID for the newly created event page
                notion.pages.update(
                    page_id=event_page['id'],  # Use event_page['id'] to update the correct page
                    properties={
                        "Course": {"rich_text": [{"text": {"content": event['course']}}]}
                    }
                )
        except Exception as e:
            print(f"Error checking for 'Course' property: {e}")

    #print(f"Finished processing events.")

# Clean up the descriptions
def clean_description(text):
    cleaned_text = re.sub(r'[\n\xa0]+', ' ', text)
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
    return cleaned_text

# Convert dates to ISO 8601 format and handle ordinal suffixes
def convert_to_iso(date_str):
    try:
        # Remove ordinal suffixes (st, nd, rd, th) from the date string
        clean_date_str = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_str)
        # Convert the cleaned date string to the desired format
        date_obj = datetime.datetime.strptime(clean_date_str, '%B %d, %Y')
        return date_obj.strftime('%Y-%m-%d')
    except ValueError as e:
        print(f"Error parsing date: {date_str}, Error: {e}")
        return date_str


# Main function
def main():
    try:
        events = scrape_calendar_with_selenium(username, password, calendar_url, login_url)
        
        if events:
            print("All events found on the calendar")
            
            # Process events (clean description and convert date)
            for event in tqdm(events, desc="Processing events", unit="event"):  # Use tqdm to display a progress bar while processing events:
                event['description'] = clean_description(event['description'])
                event['date'] = convert_to_iso(event['date'])

            print("Adding events to Notion...")
            
            # Use tqdm to display a progress bar while adding events to Notion
            for event in tqdm(events, desc="Adding events to Notion", unit="event"):
                # Call the add_to_notion for each event
                add_to_notion([event])  # Pass event as a list

        else:
            print("No events found on the calendar.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
