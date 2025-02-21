from pdf2docx import Converter

# Specify the file paths
pdf_file = 'Abdul_Muhaimin_Salay_Kanton_-_Frontend_Developer.pdf'
word_file = 'Abdul_Muhaimin_Salay_Kanton_-_Frontend_Developer.docx'

# Create a Converter object
cv = Converter(pdf_file)

# Convert the PDF to a Word document
cv.convert(word_file, start=0, end=None)

# Close the Converter object
cv.close()
