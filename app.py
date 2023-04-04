import os
import json
import urllib.request
import pypdfium2 as pdfium
from flask_mysqldb import MySQL,MySQLdb
from flask import Flask, request, json, render_template, redirect, jsonify

app = Flask(__name__)
app.config["MYSQL_HOST"] = "localhost"
app.config["MYSQL_USER"] = "root"
app.config["MYSQL_PASSWORD"] = ""
app.config["MYSQL_DB"] = "inecdb"
app.config["MYSQL_CURSORCLASS"] = "DictCursor"
mysql = MySQL(app)

app.config["SECRET_KEY"] = "add your key here" 


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # Get data from the form
        state = request.form["state"]
        lga = request.form["lga"]
        ward = request.form["ward"]
        pu_code = request.form["pu_code"]
        registered_voters = request.form["registered_voters"]
        accredited_voters = request.form["accredited_voters"]
        mutilated = request.form["mutilated"]
        is_result_sheet = request.form["is_result_sheet"]
        is_stamped = request.form["is_stamped"]
        APC = request.form["APC"]
        APC_agent_signed = request.form["APC_agent_signed"]
        LP = request.form["LP"]
        LP_agent_signed = request.form["LP_agent_signed"]
        PDP = request.form["PDP"]
        PDP_agent_signed = request.form["PDP_agent_signed"]
        NNPP = request.form["NNPP"]
        NNPP_agent_signed = request.form["NNPP_agent_signed"]
        result_file_url = request.form["result_file_url"]

        # Insert the data into the "transcribed" table
        cursor = mysql.connection.cursor()
        query = "INSERT INTO transcribed (state, lga, ward, pu_code, registered_voters, accredited_voters, mutilated, is_result_sheet, is_stamped, APC, APC_agent_signed, LP, LP_agent_signed, PDP, PDP_agent_signed, NNPP, NNPP_agent_signed, result_file_url) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        values = (state, lga, ward, pu_code, registered_voters, accredited_voters, mutilated, is_result_sheet, is_stamped, APC, APC_agent_signed, LP, LP_agent_signed, PDP, PDP_agent_signed, NNPP, NNPP_agent_signed, result_file_url)
        cursor.execute(query, values)
        mysql.connection.commit()
        message = "Data saved successfully"
        
    else: # GET request
        # Get URL and polling unit code from the "wards" table
        cursor = mysql.connection.cursor()
        query = "SELECT result_file_url, pu_code FROM wards WHERE id = 1" # replace 1 with appropriate ward id
        cursor.execute(query)
        row = cursor.fetchone()
        result_file_url = row["result_file_url"]
        pu_code = row["pu_code"]
        
        # Check if the URL and pu_code already exist in the "transcribed" table
        query = "SELECT COUNT(*) as count FROM transcribed WHERE result_file_url = %s AND pu_code = %s"
        values = (result_file_url, pu_code)
        cursor.execute(query, values)
        count = cursor.fetchone()["count"]
        
        while count > 0:
            # If the URL and pu_code exist in the "transcribed" table, get another URL and pu_code from the "wards" table
            row = cursor.fetchone()
            result_file_url = row["result_file_url"]
            pu_code = row["pu_code"]
            
            # Check if the new URL and pu_code exist in the "transcribed" table
            query = "SELECT COUNT(*) as count FROM transcribed WHERE result_file_url = %s AND pu_code = %s"
            values = (result_file_url, pu_code)
            cursor.execute(query, values)
            count = cursor.fetchone()["count"]
        
        # If the URL ends with ".pdf", download and convert to JPEG
        if result_file_url.endswith(".pdf"):
            pdf_path = os.path.join("static/cached_pdf", f"{pu_code}.pdf")
            if not os.path.exists(pdf_path):
                urllib.request.urlretrieve(result_file_url, pdf_path)
            image_path = convert_pdf_to_jpg(pdf_path, pu_code)
        else:
            image_path = result_file_url
        
        # Handle getting the states for the form field
        state_cursor = mysql.connection.cursor()
        state_query = "SELECT * FROM states"
        state_cursor.execute(state_query)
        states = state_cursor.fetchall()
        
        return render_template("index.html", image_path=image_path, states=states)

        
       


#API for List of LGAs
@app.route("/lga/<state_id>/", methods=["GET", "POST"])
def fetch_lgas(state_id):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    result = cur.execute("SELECT DISTINCT lga_id, lga_name FROM wards WHERE state_id = %s", [state_id])
    lgas = cur.fetchall()  
    lgasArray = []
    for row in lgas:
        lgasObj = {
                'id': row['lga_id'],
                'name': row['lga_name']}
        lgasArray.append(lgasObj)
    return jsonify({'lgas_json' : lgasArray})

#API for List of Wards
@app.route("/ward/<lga_id>/", methods=["GET", "POST"])
def fetch_wards(lga_id):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    result = cur.execute("SELECT DISTINCT ward_id, ward_name FROM wards WHERE lga_id = %s", [lga_id])
    wards = cur.fetchall()
    wardsArray = []
    for row in wards:
        wardsObj = {
                'id': row['ward_id'],
                'name': row['ward_name']}
        wardsArray.append(wardsObj)
    return jsonify({'wards_json' : wardsArray})

#API for List of Wards
@app.route("/pu/<ward_id>/", methods=["GET", "POST"])
def fetch_pus(ward_id):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    result = cur.execute("SELECT * FROM wards WHERE ward_id = %s", [ward_id])
    pus = cur.fetchall()
    pusArray = []
    for row in pus:
        pusObj = {
                'id': row['pu_id'],
                'name': row['pu_code']}
        pusArray.append(pusObj)
    return jsonify({'pus_json' : pusArray})

# Convert PDF to JPG using the Wand library
def convert_pdf_to_jpg(file_path, PU_Code):
    """
    This function uses wand to read the PDF file and convert each page to a JPEG image. 
    The resulting JPEG images are saved to a directory called "results" and named according to the PU_Code parameter and page number. 
    The function returns the file path of the first JPEG image.

    :param file_path: str, is the complete path to the pdf file.
    :param PU_Code: str, is the PU_Code of the result in the pdf file to be converted.
    :return: str, path to th converted image file. 
    """
    # Load a document
    pdf = pdfium.PdfDocument(file_path)

        # Create a directory to store the converted images
    if not os.path.exists("static/results"):
        os.makedirs("static/results")

    # render a single page (in this case: the first one)
    page = pdf[0]
    pil_image = page.render(scale=2).to_pil()
    pil_image.save(f"static/results/{PU_Code}.jpg")
 
 

    
    # Return the file path of the image
    return f"static/results/{PU_Code}.jpg"






if __name__ == "__main__":
    app.run(host="0.0.0.0", debug="True")
