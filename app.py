import os
import re
import json
import time
import random
import string
import mailjet_rest
from functools import wraps
from datetime import timedelta
from passlib.hash import sha256_crypt
import urllib.request
import pypdfium2 as pdfium
from flask_mysqldb import MySQL,MySQLdb
from flask import Flask, request, json, flash, url_for, render_template, redirect, jsonify, session

app = Flask(__name__)
app.config["MYSQL_HOST"] = "localhost"
app.config["MYSQL_USER"] = "root"
app.config["MYSQL_PASSWORD"] = ""
app.config["MYSQL_DB"] = "inecdb"
app.config["MYSQL_CURSORCLASS"] = "DictCursor"
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
mysql = MySQL(app)

app.config["SECRET_KEY"] = "add your key here" 

# Create an instance of the Mailjet API
apikey = "public_key"
apisecret = "private_key"
mj = mailjet_rest.Client(
    auth=(apikey,apisecret), 
    version='v3.1')

# Define the function to control user roles
def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if "logged_in" in session:
            return f(*args, **kwargs)
        else:
            flash("Unauthorized, please login.", "danger")
            return redirect(url_for("login"))
        
    return wrap

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/transcribe/", methods=["GET", "POST"])
@login_required
def transcribe():
    if request.method == "POST":
        # Get username
        username = session["username"]
        # Get data from the form
        state_id = int(request.form["state"])
        lga_id = int(request.form["lga"])
        ward_id = int(request.form["ward"])
        pu_id = int(request.form["pu"])

        raw_data = fetch_pus(ward_id)
        json_data = raw_data.json
        for data in json_data["pus_json"]:
            if data['id'] == pu_id:
                filter_data = data
                break

        # filter_data = next((data for data in json_data["pus_json"] if data["id"] == pu_id), None)
        state = filter_data["state_name"] if filter_data else None
        lga = filter_data["lga_name"] if filter_data else None
        ward = filter_data["ward_name"] if filter_data else None
        pu_code = filter_data["name"] if filter_data else None


        registered_voters = request.form["registered_voters"]
        accredited_voters = request.form["accredited_voters"]
        mutilated = request.form["mutilated"]
        if accredited_voters != None:
            is_result_sheet = True
        else:
            is_result_sheet = False
        if "is_stamped" in request.form:
            is_stamped = True
        else:
            is_stamped = False
        APC = request.form["APC"]
        APC_agent_signed = True if "APC_agent_signed" in request.form else False
        LP = request.form["LP"]
        LP_agent_signed = True if "LP_agent_signed" in request.form else False
        PDP = request.form["PDP"]
        PDP_agent_signed = True if "PDP_agent_signed" in request.form else False
        NNPP = request.form["NNPP"]
        NNPP_agent_signed = True if "NNPP_agent_signed" in request.form else False
        result_file_url = request.form["result_file_url"]

        # Insert the data into the "transcribed" table
        cursor = mysql.connection.cursor()
        query = "INSERT INTO transcribed (state, lga, ward, pu_code, registered_voters, accredited_voters, mutilated, is_result_sheet, is_stamped, APC, APC_agent_signed, LP, LP_agent_signed, PDP, PDP_agent_signed, NNPP, NNPP_agent_signed, result_file_url, username) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        values = (state, lga, ward, pu_code, registered_voters, accredited_voters, mutilated, is_result_sheet, is_stamped, APC, APC_agent_signed, LP, LP_agent_signed, PDP, PDP_agent_signed, NNPP, NNPP_agent_signed, result_file_url, username)
        cursor.execute(query, values)
        mysql.connection.commit()
        message = "Data saved successfully"

        return redirect(url_for("transcribe"))
        
    else: # GET request
        # Get URL and polling unit code from the "wards" table
        cursor = mysql.connection.cursor()
        ward_id = random.randint(1, 176851)

        result_file_url = None
        pu_code = None
        while result_file_url is None or pu_code is None:
            query = f"SELECT result_file_url, pu_code FROM wards WHERE id = {ward_id} AND result_file_url IS NOT NULL AND pu_code IS NOT NULL" # id is randomly appropriate ward id
            cursor.execute(query)
            row = cursor.fetchone()

            if row is not None:
                result_file_url = row["result_file_url"]
                pu_code = row["pu_code"]
                
                # Check if the URL and pu_code already exist in the "transcribed" table
                query = "SELECT COUNT(*) as count FROM transcribed WHERE result_file_url = %s AND pu_code = %s"
                values = (result_file_url, pu_code)
                cursor.execute(query, values)
                count = cursor.fetchone()["count"]
                
                if count > 0:
                    result_file_url = None
                    pu_code = None
                    
            # Generate a new random ward_id if the query returned no results or if the URL and pu_code already exist in the "transcribed" table
            if result_file_url is None or pu_code is None:
                ward_id = random.randint(1, 176851)

        # If the URL ends with ".pdf", download and convert to JPEG
        if result_file_url is not None:
            if result_file_url.endswith(".pdf"):
                pdf_path = os.path.join("static/cached_pdf/", f"{pu_code}.pdf")
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

        return render_template("transcribe.html", image_path=image_path, states=states, result_file_url=result_file_url)


        
@app.route("/faq/")
def faq():
    return render_template("faq.html")

@app.route("/about/")
def about():
    return render_template("about.html")


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
                'name': row['pu_code'],
                'state_name': row['state_name'],
                'lga_name': row['lga_name'],
                'ward_name': row['ward_name']}
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
    print(file_path)    
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
    return f"../static/results/{PU_Code}.jpg"

# Add a new route to the Flask application to handle the user signup form.
@app.route("/signup/", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        # Handle form submission
        username = request.form.get("username")
        raw_password = request.form.get("password")
        email = request.form.get("email")
        joined_at = time.time()

        # Validate the data
        if not username or not raw_password or not email:
            flash("All fields are required!", "warning")
        elif not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash("Please enter a valid email address!", "warning")
        else:
            # Hash paswword
            password = sha256_crypt.hash(raw_password)
            # Create the user
            try:
                conn = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
                conn.execute("INSERT INTO users (username, password, email, joined_at) VALUES (%s, %s, %s, %s)",
                        (username, password, email, joined_at))
                mysql.connection.commit()
                flash("You have successfully registered!", "success")
                return redirect(url_for("login"))
            except:
                flash("The email address is already in use!", "danger")
            mysql.connection.close()
    return render_template("signup.html")


# Add a new route to the Flask application to handle the user login form.
@app.route("/login/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # Handle form submission
        username = request.form["username"]
        password_supplied = str(request.form["password"])

        # Check if the user exists
        conn = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        result = conn.execute("SELECT * FROM users WHERE username = %s", [username])
        user = conn.fetchone()

        if user is not None:

            password = user["password"]
            app.logger.info(password)
            app.logger.info(password_supplied)
            # Validate the data
            if sha256_crypt.verify(password_supplied, password):

                # Log the user in
                session["logged_in"] = True
                session["username"] = username

                if user["name"] != None:
                    session["name"] = user["name"]
                else:
                    session["name"] = ""

                flash("You are now logged in.", "success")
                return redirect(url_for("dashboard"))
            else:
                app.logger.info("I got here.")
                flash("Invalid username or password")
                return redirect(url_for("login"))

        else:
            error = "Username does not exist"
            return render_template("login.html", error=error)

    return render_template("login.html")

# Logout route
@app.route("/logout/")
@login_required
def logout():
    session.clear()
    flash("You are now logged out", "success")
    return redirect(url_for("index"))

# Add a new route to the Flask application to handle the user dashboard page.
@app.route("/dashboard/")
@login_required
def dashboard():
    # Fetch the user's transcriptions
    conn = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    transcriptions = conn.execute("SELECT * FROM transcribed WHERE username=%s", (session["username"],))
    results = conn.fetchall()

    if transcriptions > 0:
        return render_template("dashboard.html", results=results)
        mysql.connection.close()
    else:
        msg = "You currently have no transcriptions done on your dashboard"
        return render_template("dashboard.html", msg=msg)


@app.route('/results/')
@login_required
def results():
    cur = mysql.connection.cursor()
    cur.execute("SELECT SUM(APC), SUM(LP), SUM(PDP), SUM(NNPP) FROM transcribed")
    results = cur.fetchone()
    cur.close()
    print(results)
    return render_template('results.html', results=results)


@app.route("/profile/<username>", methods=["GET", "POST"])
@login_required
def profile(username):
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM users WHERE username = %s", [username])
    user = cur.fetchone()

    if request.method == "POST":
        # Get the uploaded image file
        image = request.files.get("image")
        if image:
            # Save the file to the /static/users folder with the username as the filename
            filename = f"{username}.png"
            image.save(os.path.join("static/users", filename))
            # Update the user's profile image URL in the database
            image_url = f"../static/users/{filename}"
            cur.execute("UPDATE users SET profile_image = %s WHERE username = %s", [image_url, username])
            session["profile_image"] = image_url
        # Update the user's other profile information in the database
        name = request.form["name"]
        gender = request.form["gender"]
        phone_number = request.form["phone_number"]
        address = request.form["address"]
        cur.execute("UPDATE users SET name = %s, gender = %s, phone_number = %s, address = %s WHERE username = %s", [name, gender, phone_number, address, username])
        mysql.connection.commit()
        return redirect(url_for("profile", username=username))
    
    cur.close()
    return render_template("profile.html", user=user)


# Password reset function
@app.route("/reset_password/", methods=["GET", "POST"])
def reset_password():
    if request.method == "POST":
        # Handle form submission
        email = request.form.get("email")

        # Check if the user exists
        conn = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        result = conn.execute("SELECT * FROM users WHERE email=%s", [email])
        user = conn.fetchone()

        if user is not None:
            # Generate a unique link
            link = generate_unique_link()
            # Send the link to the user's email
            status = send_password_reset_email(email, link)
            if status == "success":
                flash("A password reset link has been sent to your email address.")
                time.sleep(3)
                return redirect(url_for("login"))
            elif status == "error":
                time.sleep(3)
                flash("An error occurred while sending the link to your email address.", "warning")
        else:
            error = "The email address does not exist in the system."
            return render_template("reset_password.html", error=error)

    return render_template("reset_password.html")

# Generate a unique link
def generate_unique_link():
    # Generate a random string
    link = "".join([random.choice(string.ascii_letters + string.digits) for n in range(32)])
    # Check if the link is already used
    conn = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    result = conn.execute("SELECT * FROM reset_password WHERE link=%s", [link])
    found = conn.fetchone()
    # If the link is already used, generate a new link
    if found is not None:
        link = generate_unique_link()
    # Return the unique link
    return link

# Send the link to the user's email
def send_password_reset_email(email, link):
    # Generate the expiration time
    expiration_time = time.time() + 1800
    # Save the link to the database
    conn = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    conn.execute("INSERT INTO reset_password (email, link, expiration_time) VALUES (%s, %s, %s)",
            (email, link, expiration_time))
    mysql.connection.commit()
    # Compose the message
    message = "Please click on the following link to reset your password.\n"
    message += "http://localhost:5000/reset_password/{}".format(link)
    # Send the message
    if send_email(email, message) == 200:
        return "success"
    else:
        return "error"

# Handle the reset password link
@app.route("/reset_password/<link>/")
def new_password(link):
    # Check if the link is valid
    conn = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    result = conn.execute("SELECT * FROM reset_password WHERE link=%s AND expiration_time>=%s", (link, time.time()))
    found = conn.fetchone()
    mysql.connection.close()
    # If the link is valid, render the new password page
    if found is not None:
        return render_template("newpassword.html", link=link)
    else:
        flash("The link is invalid or expired.")
        return redirect(url_for("login"))

# Handle the new password form
@app.route("/reset_password/<link>/submit", methods=["POST"])
def reset_password_submit(link):
    # Handle form submission
    new_password = request.form.get("new_password")
    confirm_new_password = request.form.get("confirm_new_password")

    # Validate the data
    if not new_password or not confirm_new_password:
        flash("All fields are required!")
    elif new_password != confirm_new_password:
        flash("Passwords do not match!")
    else:
        # Hash the new password
        password = sha256_crypt.hash(new_password)
        # Get the user's email
        conn = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        result = conn.execute("SELECT * FROM reset_password WHERE link=%s", (link))
        found = conn.fetchone()
        mysql.connection.close()
        email = found["email"]
        # Update the user's password
        conn = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        conn.execute("UPDATE users SET password=%s WHERE email=%s", (password, email))
        mysql.connection.commit()
        mysql.connection.close()
        # Delete the reset password entry
        conn = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        conn.execute("DELETE FROM reset_password WHERE link=%s", [link])
        mysql.connection.commit()
        mysql.connection.close()
        # Log the user in
        session["logged_in"] = True
        session["username"] = username

        flash("Your password has been successfully reset.")
        return redirect(url_for("dashboard"))

    return render_template("newpassword.html", link=link)


# Send email function
def send_email(email, message):
    data = {
        'Messages': [
        {
            "From": {
                "Email": "no-reply@citidient.org",
            },
            "To": [
                {
                    "Email": email
                }
            ],
            "Subject": "Password Reset",
            "TextPart": message
        }
        ]
    }
    result = mj.send.create(data=data)
    return result.status_code




if __name__ == "__main__":
    app.run(host="0.0.0.0", debug="True")
