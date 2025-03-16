from flask import Flask, render_template, request, redirect, url_for, session, flash,jsonify
from flask import get_flashed_messages
from flask_paginate import Pagination, get_page_parameter
import pyodbc
import pandas as pd
import pickle
app = Flask(__name__)
app.secret_key = 'YOUR_SECRET_KEY'
model_path = 'svd_model.pkl'

@app.before_request
def require_login():
    allowed_routes = ['login', 'static']  # Add other routes that don't require login if necessary
    if 'user_id' not in session and request.endpoint not in allowed_routes:
        return redirect(url_for('login'))

with open(model_path, 'rb') as file:
    model = pickle.load(file)
# Database information
DATABASE = 'DBFinal21'
USERNAME = 'nz'
PASSWORD = '1q1q1q1q'
DRIVER = 'SQL Server'
SERVER = 'DESKTOP-2TE06S1\SQLEXPRESS02'

# Database connection function
def get_db_connection():
    conn_str = (
        f'DRIVER={{{DRIVER}}};'
        f'SERVER={SERVER};'
        f'DATABASE={DATABASE};'
        f'UID={USERNAME};'
        f'PWD={PASSWORD}'
    )
    return pyodbc.connect(conn_str)

@app.route('/login', methods=['GET', 'POST'])
def login():
    session.clear() 
    error = None
    if request.method == 'POST':
        user_id = request.form['username']
        password = request.form['password']

        # Kiểm tra xem user_id có phải là số nguyên hợp lệ
        try:
            user_id_int = int(user_id)
        except ValueError:
            error = 'User ID must be an integer.'
            return render_template('login.html', error=error)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT User_ID FROM Users WHERE User_ID = ?", (user_id_int,))
        result = cursor.fetchone()
        conn.close()

        if result and password == 'Abc@123':  # User exists and password is correct
            session['user_id'] = user_id
            return redirect(url_for('home'))
        else:
            error = 'Invalid User ID or Password.'
    return render_template('login.html', error=error)


@app.route('/')
def home():
    user_id = session.get('user_id')    
    if not user_id:
        return redirect(url_for('login'))

    # Lấy thông tin sách và đánh giá từ cơ sở dữ liệu
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Books WHERE Image_URL_S != '122002'")
    books = cursor.fetchall()
    books_list = list(map(list, books))
    books_df = pd.DataFrame(books_list, columns=['ISBN', 'Book_Title', 'Book_Author', 'Year_Of_Publication', 'Publisher',
                                            'Image_URL_S', 'Image_URL_M', 'Image_URL_L'])

    # Lấy các ISBN mà người dùng đã đọc
    cursor.execute('SELECT ISBN FROM Ratings WHERE User_ID = ?', (user_id,))
    read_books_isbn = [row.ISBN for row in cursor.fetchall()]

    # Lọc sách mà người dùng chưa đọc và tạo dự đoán
    unread_books = books_df[~books_df['ISBN'].isin(read_books_isbn)]
    predictions = []
    for isbn in unread_books['ISBN']:
        predictions.append((isbn, model.predict(uid=user_id, iid=isbn).est))

    # Sắp xếp dựa trên dự đoán và lấy top N
    predictions.sort(key=lambda x: x[1], reverse=True)
    top_n_predictions = predictions[:10]

    recommended_books_info = []
    for isbn, _ in top_n_predictions:
        book_info = unread_books[unread_books['ISBN'] == isbn].iloc[0]
        recommended_books_info.append(book_info)

    recommended_books = []
    for book in recommended_books_info:
        recommended_books.append({
            'ISBN': book['ISBN'],
            'Book_Title': book['Book_Title'],
            'Book_Author': book['Book_Author'],
            'Image_URL_L': book['Image_URL_L']
        })

    cursor.execute(
        'SELECT Books.ISBN, Book_Title,Book_Author, Image_URL_L FROM Books JOIN Ratings ON Books.ISBN = Ratings.ISBN WHERE User_ID = ?',
        (user_id,))
    read_books = [{'ISBN': row.ISBN, 'Book_Title': row.Book_Title, 'Image_URL_L': row.Image_URL_L,'Book_Author':row.Book_Author} for row in
                  cursor.fetchall()]

    conn.close()

    # Gửi thông tin đến template
    return render_template('home.html', user_id=user_id, read_books=read_books, recommended_books=recommended_books)

@app.route('/book/<isbn>', methods=['GET', 'POST'])
def book_detail(isbn):
    user_id = session.get('user_id')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT ISBN, Book_Title, Book_Author, Year_Of_Publication, Publisher,
        Image_URL_S, Image_URL_M, Image_URL_L FROM Books WHERE ISBN = ?""", (isbn,))
    book_row = cursor.fetchone()

    if book_row is None:
        flash("Book not found.", "warning")
        return redirect(url_for('home'))

    book_info = {
        'ISBN': book_row.ISBN,
        'Book_Title': book_row.Book_Title,
        'Book_Author': book_row.Book_Author,
        'Year_Of_Publication': book_row.Year_Of_Publication,
        'Publisher': book_row.Publisher,
        'Image_URL_S': book_row.Image_URL_S,
        'Image_URL_M': book_row.Image_URL_M,
        'Image_URL_L': book_row.Image_URL_L
    }

    cursor.execute("""
        SELECT COUNT(Book_Rating) AS rating_count, AVG(Book_Rating) AS avg_rating
        FROM Ratings WHERE ISBN = ? GROUP BY ISBN""", (isbn,))
    ratings_result = cursor.fetchone()
    rating_count = ratings_result.rating_count if ratings_result else 0
    avg_rating = ratings_result.avg_rating if ratings_result else 0

    if request.method == 'POST':
        rating = int(request.form['rating'])
        cursor.execute("SELECT * FROM Ratings WHERE User_ID = ? AND ISBN = ?", (user_id, isbn))
        existing_rating = cursor.fetchone()

        if existing_rating:
            cursor.execute("UPDATE Ratings SET Book_Rating = ? WHERE User_ID = ? AND ISBN = ?", (rating, user_id, isbn))
        else:
            cursor.execute("INSERT INTO Ratings (User_ID, ISBN, Book_Rating) VALUES (?, ?, ?)", (user_id, isbn, rating))

        conn.commit()
        flash('Your rating has been submitted.', 'success')

    # Fetch user's collections
    cursor.execute("""
        SELECT c.ID, c.name, 
               CASE WHEN bic.ISBN IS NOT NULL THEN 1 ELSE 0 END AS Has_Book
        FROM collections c
        LEFT JOIN books_in_collections bic ON c.ID = bic.collection_id AND bic.ISBN = ?
        WHERE c.User_ID = ?""", (isbn, user_id))
    collections = cursor.fetchall()

    user_collections = [{'id': row.ID, 'name': row.name, 'has_book': bool(row.Has_Book)} for row in collections]

    conn.close()
    return render_template('book_detail.html', book=book_info, rating_count=rating_count, avg_rating=avg_rating, collections=user_collections)

@app.route('/add_to_collection', methods=['POST'])
def add_to_collection():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify(message="Please log in to add books to collections."), 401

    book_isbn = request.form.get('book_isbn')
    selected_collections = request.form.getlist('collections')

    conn = get_db_connection()
    cursor = conn.cursor()

    for collection_id in selected_collections:
        cursor.execute("""
            IF NOT EXISTS (SELECT 1 FROM books_in_collections WHERE collection_id = ? AND ISBN = ?)
            INSERT INTO books_in_collections (collection_id, ISBN) VALUES (?, ?)""",
            (collection_id, book_isbn, collection_id, book_isbn))

    conn.commit()
    conn.close()

    return jsonify(message="Book added to selected collections successfully")

# Route for displaying all collections
@app.route('/collections', methods=['GET', 'POST'])
def collections():
    conn = get_db_connection()
    cursor = conn.cursor()
    user_id = session['user_id']  # Assuming user_id is stored in session
    
    if request.method == 'POST':
        name = request.form['name']
        is_public = 'is_public' in request.form
        cursor.execute("INSERT INTO collections (name, User_ID, is_public) VALUES (?, ?, ?)", (name, user_id, is_public))
        conn.commit()
    
    cursor.execute("SELECT * FROM collections WHERE User_ID = ?", (user_id,))
    collections = cursor.fetchall()
    conn.close()
    return render_template('collections.html', collections=collections)

@app.route('/search_public_collections', methods=['GET'])
def search_public_collections():
    user_id = request.args.get('user_id')
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Debugging print statements
    print(f"Searching for public collections of user: {user_id}")
    
    cursor.execute("SELECT * FROM collections WHERE User_ID = ? AND is_public = 1", (user_id,))
    public_collections = cursor.fetchall()
    
    # Print the results fetched from the database
    print(f"Public collections found: {public_collections}")
    
    conn.close()
    
    if public_collections:
        return render_template('collection_search.html', collections=public_collections, user_id=user_id)
    else:
        flash(f'No public collections from user: {user_id}', 'danger')
        return redirect(url_for('collections'))
    
# Route for displaying collection details and editing
@app.route('/collection/<int:id>', methods=['GET', 'POST'])
def collection_detail(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    user_id = session['user_id']  # Assuming user_id is stored in session

    # Fetch collection details
    cursor.execute("SELECT * FROM collections WHERE ID = ? AND (User_ID = ? OR is_public = 1)", (id, user_id))
    collection = cursor.fetchone()

    print(f"user_id from session: {user_id}, collection user_id: {collection.User_ID}")
    if str(collection.User_ID) != str(user_id):
        return redirect(url_for('view_collection', id=id))


    if not collection:
        flash("You do not have access to this collection", "danger")
        return redirect(url_for('collections'))

    if request.method == 'POST':
        name = request.form['name']
        is_public = 1 if 'is_public' in request.form else 0
        cursor.execute("UPDATE collections SET name = ?, is_public = ? WHERE ID = ?", (name, is_public, id))
        conn.commit()
        return redirect(url_for('collection_detail', id=id))

    # Fetch books in the collection
    cursor.execute("""
        SELECT Books.* 
        FROM Books
        INNER JOIN books_in_collections ON Books.ISBN = books_in_collections.ISBN
        WHERE books_in_collections.collection_id = ?
    """, (id,))
    books = cursor.fetchall()

    conn.close()
    return render_template('collection_detail.html', collection=collection, books=books)


@app.route('/collection/view/<int:id>', methods=['GET'])
def view_collection(id):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch collection details
    cursor.execute("SELECT * FROM collections WHERE ID = ? AND is_public = 1", (id,))
    collection = cursor.fetchone()

    if not collection:
        flash("This collection is not public or does not exist", "danger")
        return redirect(url_for('collections'))

    # Fetch books in the collection
    cursor.execute("""
        SELECT Books.* 
        FROM Books
        INNER JOIN books_in_collections ON Books.ISBN = books_in_collections.ISBN
        WHERE books_in_collections.collection_id = ?
    """, (id,))
    books = cursor.fetchall()

    conn.close()
    return render_template('view_collection.html', collection=collection, books=books)


# Route to add a book to a collection
@app.route('/collection/<int:id>/add_book', methods=['POST'])
def add_book_to_collection(id):
    isbn = request.form['isbn']
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if the book is already in the collection
    cursor.execute("""
        SELECT 1 FROM books_in_collections WHERE collection_id = ? AND ISBN = ?
    """, (id, isbn))
    if cursor.fetchone():
        flash('Book already exists in the collection.', 'info')
        return redirect(url_for('collection_detail', id=id))

    # Insert the book into the collection if it does not exist
    cursor.execute("""
        INSERT INTO books_in_collections (collection_id, ISBN) VALUES (?, ?)
    """, (id, isbn))
    conn.commit()
    conn.close()

    flash('Book added to collection successfully.', 'success')
    return redirect(url_for('collection_detail', id=id))

# Route to remove a book from a collection
@app.route('/collection/<int:id>/remove_book/<string:isbn>', methods=['POST'])
def remove_book_from_collection(id, isbn):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM books_in_collections WHERE collection_id = ? AND ISBN = ?", (id, isbn))
    conn.commit()
    pass
    return redirect(url_for('collection_detail', id=id))

def search_books(query):
    conn = get_db_connection()
    cursor = conn.cursor()
    search_query = """
        SELECT ISBN, Book_Title, Book_Author, Image_URL_L 
        FROM Books 
        WHERE LOWER(ISBN) LIKE ? OR LOWER(Book_Title) LIKE ? OR LOWER(Book_Author) LIKE ?
    """
    wildcard_query = f'%{query.lower()}%'  # Convert the search query to lowercase
    cursor.execute(search_query, (wildcard_query, wildcard_query, wildcard_query))
    results = cursor.fetchall()
    conn.close()
    
    books = []
    for row in results:
        book = {
            'ISBN': row[0],  # Update to access tuple elements
            'Book_Title': row[1],
            'Book_Author': row[2],
            'Image_URL_L': row[3]
        }
        books.append(book)
    
    return books

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('data')
    search_results = search_books(query)
    return render_template('search_results.html', search_results=search_results)

@app.route('/a-z',methods=['GET'])
def a_z():
    page = request.args.get(get_page_parameter(), type=int, default=1)
    per_page = 20
    offset = (page - 1) * per_page

    # Establish database connection
    connection = get_db_connection()
    cursor = connection.cursor()

    # Fetch books ordered by title with pagination
    cursor.execute("SELECT * FROM Books ORDER BY Book_Title OFFSET ? ROWS FETCH NEXT ? ROWS ONLY", (offset, per_page))
    books = cursor.fetchall()

    # Total count of books for pagination
    cursor.execute("SELECT COUNT(*) FROM Books")
    total_books = cursor.fetchone()[0]

    # Close the cursor and connection
    cursor.close()
    connection.close()

    # Pagination object
    pagination = Pagination(page=page, total=total_books, search=False, record_name='books', per_page=per_page, css_framework='bootstrap4', show_single_page=False)

    return render_template('a-z.html', all_books=books, pagination=pagination)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == "admin" and password == "admin":
            session['admin'] = True
            flash("Successful login as admin.", "success")
            return redirect(url_for('admin_books'))
        else:
            flash("Invalid admin credentials.", "danger")

    return render_template('admin_login.html')


# Giả sử bạn đã định nghĩa hàm get_db_connection() và bạn đã thiết lập kết nối cơ sở dữ liệu
@app.route('/admin/books')
def admin_books():
    if not session.get('admin'):
        flash("Access denied. Please log in as an admin.", "danger")
        return redirect(url_for('login'))

    search_query = request.args.get('search')
    conn = get_db_connection()
    cursor = conn.cursor()

    if search_query:
        # Prepare the query to be case insensitive and filter out specific image URL
        cursor.execute("""
            SELECT TOP(1000) ISBN, Book_Title, Book_Author, Year_Of_Publication, Publisher, Image_URL_S, Image_URL_M, Image_URL_L 
            FROM Books 
            WHERE LOWER(Book_Title) LIKE ? AND Image_URL_S != '122002'
            """, ('%' + search_query.lower() + '%',))
    else:
        # Fetch books excluding specific image URL
        cursor.execute("""
            SELECT TOP(1000) ISBN, Book_Title, Book_Author, Year_Of_Publication, Publisher, Image_URL_S, Image_URL_M, Image_URL_L 
            FROM Books
            WHERE Image_URL_S != '122002'
            """)

    books = cursor.fetchall()
    conn.close()
    return render_template('admin_books.html', books=books, search_query=search_query)

@app.route('/admin/book/delete', methods=['POST'])
def delete_book():
    if not session.get('admin'):
        return jsonify({"error": "Access denied"}), 403

    isbn = request.form.get('isbn')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE Books SET Image_URL_S = '122002' WHERE ISBN = ?", (isbn,))
    conn.commit()
    conn.close()
    flash("Book marked as deleted successfully.", "success")
    return redirect(url_for('admin_books'))

@app.route('/admin/book/edit', methods=['POST'])
def edit_book():
    if not session.get('admin'):
        return jsonify({"error": "Access denied"}), 403

    # Lấy dữ liệu từ form
    isbn = request.form.get('isbn')
    book_title = request.form['book_title']
    book_author = request.form['book_author']
    year_of_publication = request.form['year_of_publication']
    publisher = request.form['publisher']
    image_url_s = request.form['image_url_s']
    image_url_m = request.form['image_url_m']
    image_url_l = request.form['image_url_l']

    # Kết nối tới cơ sở dữ liệu và cập nhật thông tin sách
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE Books 
        SET Book_Title = ?, Book_Author = ?, Year_Of_Publication = ?, Publisher = ?, 
            Image_URL_S = ?, Image_URL_M = ?, Image_URL_L = ? 
        WHERE ISBN = ?""",
                   (book_title, book_author, year_of_publication, publisher, image_url_s, image_url_m, image_url_l, isbn))
    conn.commit()
    conn.close()
    flash("Book updated successfully.", "success")
    return redirect(url_for('admin_books'))


@app.route('/admin/book/create', methods=['POST'])
def create_book():
    if not session.get('admin'):
        return jsonify({"error": "Access denied"}), 403

    isbn = request.form.get('isbn')
    book_title = request.form['book_title']
    book_author = request.form['book_author']
    year_of_publication = request.form['year_of_publication']
    publisher = request.form['publisher']
    image_url_s = request.form['image_url_s']
    image_url_m = request.form['image_url_m']
    image_url_l = request.form['image_url_l']

    conn = get_db_connection()
    cursor = conn.cursor()

    # Kiểm tra ISBN đã tồn tại chưa
    cursor.execute("SELECT ISBN FROM Books WHERE ISBN = ?", (isbn,))
    existing_isbn = cursor.fetchone()

    if existing_isbn:
        flash("ISBN đã tồn tại. Vui lòng nhập ISBN khác.", "danger")
        conn.close()
        return redirect(url_for('admin_books'))

    # Thêm sách vào cơ sở dữ liệu
    cursor.execute("""
        INSERT INTO Books (ISBN, Book_Title, Book_Author, Year_Of_Publication, Publisher, Image_URL_S, Image_URL_M, Image_URL_L) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (isbn, book_title, book_author, year_of_publication, publisher, image_url_s, image_url_m, image_url_l))

    conn.commit()
    conn.close()
    flash("Sách mới đã được thêm thành công.", "success")
    return redirect(url_for('admin_books'))
@app.route('/admin/users')
def admin_users():
    if not session.get('admin'):
        flash("Access denied. Please log in as an admin.", "danger")
        return redirect(url_for('admin_login'))

    search_query = request.args.get('search', '')  # Lấy tham số tìm kiếm từ URL
    conn = get_db_connection()
    cursor = conn.cursor()

    if search_query:
        # Tìm kiếm người dùng dựa trên tham số tìm kiếm
        # Điều chỉnh truy vấn dựa trên cách bạn muốn tìm kiếm (ví dụ: tìm kiếm theo User_ID, Location, hoặc Age)
        cursor.execute("SELECT TOP(1000) User_ID, Location, Age FROM Users WHERE (Age != 122002 OR Age IS NULL) AND (User_ID LIKE ? OR Location LIKE ?)", ('%' + search_query + '%', '%' + search_query + '%'))
    else:
        # Nếu không có tham số tìm kiếm, lấy tất cả người dùng
        cursor.execute("SELECT TOP(1000) User_ID, Location, Age FROM Users WHERE Age != 122002 OR Age IS NULL")

    users = cursor.fetchall()
    conn.close()
    return render_template('admin_users.html', users=users, search_query=search_query)
@app.route('/admin/user/edit', methods=['POST'])
def edit_user():
    if not session.get('admin'):
        return jsonify({"error": "Access denied"}), 403

    user_id = request.form.get('user_id')
    location = request.form['location']
    age = request.form['age']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("UPDATE Users SET Location = ?, Age = ? WHERE User_ID = ?", (location, age, user_id))
    conn.commit()
    conn.close()
    flash("User updated successfully.", "success")
    return redirect(url_for('admin_users'))
@app.route('/admin/user/delete', methods=['POST'])
def delete_user():
    if not session.get('admin'):
        return jsonify({"error": "Access denied"}), 403

    user_id = request.form.get('user_id')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("UPDATE Users SET Age = 122002 WHERE User_ID = ?", (user_id,))
    conn.commit()
    conn.close()
    flash("User marked as deleted successfully.", "success")
    return redirect(url_for('admin_users'))
@app.route('/admin/user/create', methods=['POST'])
def create_user():
    if not session.get('admin'):
        return jsonify({"error": "Access denied"}), 403

    user_id = request.form.get('user_id')
    location = request.form['location']
    age = request.form['age']

    conn = get_db_connection()
    cursor = conn.cursor()

    # Kiểm tra xem User_ID đã tồn tại chưa
    cursor.execute("SELECT User_ID FROM Users WHERE User_ID = ?", (user_id,))
    if cursor.fetchone():
        flash("User ID already exists.", "danger")
        conn.close()
        return redirect(url_for('admin_users'))

    cursor.execute("INSERT INTO Users (User_ID, Location, Age) VALUES (?, ?, ?)", (user_id, location, age))
    conn.commit()
    conn.close()
    flash("New user created successfully.", "success")
    return redirect(url_for('admin_users'))
@app.route('/get-flash-messages')
def get_flash_messages():
    messages = get_flashed_messages(with_categories=True)
    return jsonify({'messages': messages})

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))
if __name__ == '__main__':
    app.run(debug=True)

