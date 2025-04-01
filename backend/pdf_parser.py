import pdfplumber
import pandas as pd

def extract_tables_from_pdf(pdf_path):
    tables = []
    
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            extracted_tables = page.extract_tables()
            
            for table_index, table in enumerate(extracted_tables):
                df = pd.DataFrame(table) 
                # df = df.dropna(how='all', axis=0).dropna(how='all', axis=1)
                tables.append((page_num, table_index, df))
    
    return tables

def print_tables(tables):
    for page_num, table_index, df in tables:
        print(f"\nTable {table_index+1} on Page {page_num}:")
        print(df.to_string(index=False, header=False))  # Print table nicely formatted

if __name__ == "__main__":
    pdf_path = "sample.pdf"  # Replace with your PDF file path
    tables = extract_tables_from_pdf(pdf_path)
    print_tables(tables)