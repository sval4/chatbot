from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.document_loaders import PyPDFLoader, DirectoryLoader, CSVLoader, UnstructuredURLLoader, TextLoader
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.vectorstores import FAISS
from langchain.docstore.document import Document

import PyPDF2
import torch
import requests
import mechanicalsoup
from bs4 import BeautifulSoup
import time
import os


DEVICE = "cpu"
if torch.cuda.is_available():
    DEVICE = "cuda"

DB_FAISS_PATH = "vectorstores/db_faiss"


master_links = set() #Keep track of all the initial links in the base url webpage
processed_links = set() #Keep track of all links that have been added into the vector db
processed_PDFs = set() #Keep track of all the pdf links that have been added into the vector db

current_base_link = ""

# Define the user-agent header for the browser request
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
}

# Create a browser object using MechanicalSoup
browser = mechanicalsoup.StatefulBrowser()

"""
Fetches all links within a given web page and appends them to the provided sets based on certain criteria.

Parameters:
base_url (str): Base URL of the page
url (str): URL of the page to fetch links from
setOfInsideLinks (set): Set to store valid internal links
setOfWrongLinks (set): Set to store invalid or broken links
browser (mechanicalsoup.StatefulBrowser): Browser object for making HTTP requests
headers (dict): HTTP headers for making requests
level (int): Current level of depth in fetching links

Returns:
None
"""
def getAllLinksInPage(base_url, url, setOfInsideLinks, setOfWrongLinks, browser, headers, level, documentList):
    global processed_links
    global processed_PDFs
    # Define the maximum level of page traversal
    max_level = 1
    delay = 2
    time.sleep(delay)

    try:
        # Fetch the webpage content from the specified URL using MechanicalSoup
        page = browser.get(url, headers=headers, timeout=5)
        
        # Check if the page or its content is not retrievable
        if page == None or page.soup == None:
            setOfWrongLinks.add(url)
            return 
        
        if page.status_code == 404:
            setOfWrongLinks.add(url)  
            print(f"404 Not Found: {url}")  
            return  
    except Exception as e:
        print(url) 
        print(f"{e}")  
        setOfWrongLinks.add(url) 
        return 

    # Find all anchor and link elements on the page and gather their 'href' attributes
    links = page.soup.find_all('a')
    links += page.soup.find_all('link')

    # Iterate through all found links
    for link in links:
        href = link.get('href') 
        
        # Format the URL link if necessary
        if href and href[-1] == "/":
            href = href[0:len(href)-1]
            
        # Filter out specific types of URLs based on certain conditions
        if href and "http" in href:
            continue
        elif href and (base_url + href).rfind("html") == (base_url + href).find("html") and \
        href.rfind("pdf") == -1 and href.rfind("png") == -1 and href.rfind("json") == -1 and href.rfind(":") == -1 and \
        href.rfind(".ico") == -1 and href.rfind(".svg") == -1 and href.rfind(".si") == -1 and href.rfind("?") == -1 and \
        href.rfind("%20") == -1 and href.rfind("#") == -1 and (base_url + href).rfind(".com") == (base_url + href).find(".com"):

            link = ""

            # Construct the absolute link from the base URL and extracted href
            if href[0] != "/" and base_url[-1] != "/":
                link = base_url + "/" + href
            elif href[0] == "/" and base_url[-1] == "/":
                link = base_url + href[1:]
            else:
                link = base_url + href

            if link in setOfWrongLinks or link in setOfInsideLinks or current_base_link not in link or link in processed_links:
                continue

            if link and ".pdf" in link:
                # Download the PDF content
                response = requests.get(href)
                with open("temp.pdf", "wb") as f:
                    f.write(response.content)

                # Read and extract text from the downloaded PDF
                pdf_file = open("temp.pdf", "rb")
                reader = PyPDF2.PdfReader(pdf_file)
                text = ""
                for num in range(len(reader.pages)):
                    page = reader.pages[num]
                    text += page.extract_text()

                # Close and remove the temporary PDF file
                pdf_file.close()
                os.remove("temp.pdf")

                # Append the extracted text as a Document object to the document list
                documentList.add(Document(page_content=text.replace("\n", "").replace("\x00", "f"), metadata={"source": href}))
                setOfInsideLinks.add(link)
                continue
            
            # If the current traversal level is less than the maximum level, continue extracting links recursively
            if level < max_level:
                getAllLinksInPage(base_url, link, setOfInsideLinks, setOfWrongLinks, browser, headers, level + 1, documentList)
            setOfInsideLinks.add(link)



def startingLinks(browser, headers):
    global processed_links
    global processed_PDFs
    listOfCenters = set()
    documentList = set()

    # Iterate through all found links
    for link in master_links:
        # Get the 'href' attribute from each link
        href = link.get('href')
        
        # Check if the link points to a PDF file
        if href and ".pdf" in href:
            # Download the PDF content
            response = requests.get(href)
            with open("temp.pdf", "wb") as f:
                f.write(response.content)

            # Read and extract text from the downloaded PDF
            pdf_file = open("temp.pdf", "rb")
            reader = PyPDF2.PdfReader(pdf_file)
            text = ""
            for num in range(len(reader.pages)):
                page = reader.pages[num]
                text += page.extract_text()

            # Close and remove the temporary PDF file
            pdf_file.close()
            os.remove("temp.pdf")

            # Append the extracted text as a Document object to the document list
            documentList.add(Document(page_content=text.replace("\n", "").replace("\x00", "f"), metadata={"source": href}))

        # Check for other types of links excluding certain domains and resources
        elif href and "http" in href:
            if current_base_link not in href or href in processed_links:
                continue
            # Initialize sets for inside and wrong links
            setOfInsideLinks = set()
            setOfWrongLinks = set()
            
            # Fetch all links within the current link recursively using a helper function
            getAllLinksInPage(href, href, setOfInsideLinks, setOfWrongLinks, browser, headers, 0, documentList)
            
            # Union of unique inside links with the overall set of centers
            listOfCenters = listOfCenters.union(setOfInsideLinks)

    processed_links = listOfCenters.union(processed_links)
    processed_PDFs = documentList.union(processed_PDFs)


def addLink(link):
    global master_links
    global current_base_link
    global processed_PDFs
    left = link.find("://")
    right = link.rfind("/")
    count = link.count("/")
    
    master_links = set()
    if right == -1:
        current_base_link = link[left + 3:]
    else:
        if right != len(link) - 1 and count > 3:
            print("Invalid URL")
            return False
        current_base_link = link[left + 3: right]

    try:
        page = browser.get(link, headers=headers, timeout=5)
    except Exception as e:
        print("Invalid URL")
        return False
    # Find all anchor elements on the webpage
    links = page.soup.find_all('a')
    links += page.soup.find_all('link')
    for link1 in links:
        master_links.add(link1)
    master_links = master_links.difference(processed_links)
    return True


def createVectorDB(link):
    # Fetch information on centers from the specified website
    startingLinks(browser, headers)

    # Display the extracted URLs
    print(processed_links)

    # Load unstructured data from URLs using a specific set of headers
    loaders = UnstructuredURLLoader(urls=processed_links, headers=headers)
    documents = loaders.load()

    # Combine loaded documents with PDF documents
    documents += processed_PDFs

    # Replace newline characters with empty strings in all document content
    for document in documents:
        document.page_content = document.page_content.replace("\n", "")

    # Split documents into smaller chunks for processing
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=50)
    texts = text_splitter.split_documents(documents)

    # Create embeddings using a pre-trained HuggingFace model
    embeddings = HuggingFaceEmbeddings(model_name='sentence-transformers/all-MiniLM-L6-v2', model_kwargs={"device": DEVICE})

    # Create a FAISS database from the document texts and embeddings
    db = FAISS.from_documents(texts, embeddings)

    # Save the FAISS database locally
    db.save_local(DB_FAISS_PATH)