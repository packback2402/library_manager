import pandas as pd
from surprise import Reader, Dataset, SVD
from surprise.model_selection import cross_validate
import os
import pickle
import pyodbc


def load_data(sql_conn, books_table, ratings_table, users_table):
    """
    Load data from SQL Server tables.

    Args:
        sql_conn (pyodbc.Connection): Connection to SQL Server.
        books_table (str): Name of the books table.
        ratings_table (str): Name of the ratings table.
        users_table (str): Name of the users table.

    Returns:
        tuple: A tuple containing three DataFrames: books_df, ratings_df, users_df.
    """
    books_df = pd.read_sql(f"SELECT * FROM {books_table}", sql_conn)
    ratings_df = pd.read_sql(f"SELECT * FROM {ratings_table}", sql_conn)
    users_df = pd.read_sql(f"SELECT * FROM {users_table}", sql_conn)
    return books_df, ratings_df, users_df

def filter_data(ratings_df, books_df, users_df):
    """
    Filter data to include valid books and users.

    Args:
        ratings_df (pd.DataFrame): The ratings DataFrame.
        books_df (pd.DataFrame): The books DataFrame.
        users_df (pd.DataFrame): The users DataFrame.

    Returns:
        pd.DataFrame: The filtered ratings DataFrame.
    """
    ratings_df = ratings_df[ratings_df['ISBN'].isin(books_df['ISBN'])]
    ratings_df = ratings_df[ratings_df['User_ID'].isin(users_df['User_ID'])]
    return ratings_df

def train_model(ratings_df, save_model=True, model_path='svd_model.pkl'):
    """
    Train SVD model and optionally save it to a file.

    Args:
        ratings_df (pd.DataFrame): The ratings DataFrame.
        save_model (bool): Whether to save the model to a file (default is True).
        model_path (str): The path to save the model file (default is 'svd_model.pkl').

    Returns:
        SVD: The trained SVD model.
    """
    reader = Reader(rating_scale=(1, 10))
    data = Dataset.load_from_df(ratings_df[['User_ID', 'ISBN', 'Book_Rating']], reader)
    model = SVD()
    cross_validate(model, data, measures=['RMSE', 'MAE'], cv=5, verbose=True)
    if save_model:
        with open(model_path, 'wb') as f:
            pickle.dump(model, f)
    return model

def recommend_books(user_id, model, books_df, ratings_df, num_recommendations=10):
    """
    Recommend books for a given user.

    Args:
        user_id (int): The ID of the user.
        model (SVD): The trained SVD model.
        books_df (pd.DataFrame): The books DataFrame.
        ratings_df (pd.DataFrame): The ratings DataFrame.
        num_recommendations (int): The number of books to recommend (default is 10).

    Returns:
        pd.DataFrame: The top recommended books DataFrame.
    """
    read_books = ratings_df[ratings_df['User_ID'] == user_id]['ISBN'].unique()
    unread_books = books_df[~books_df['ISBN'].isin(read_books)]
    predictions = [model.predict(user_id, isbn).est for isbn in unread_books['ISBN']]
    recommendations_df = pd.DataFrame({'ISBN': unread_books['ISBN'], 'Predicted_Rating': predictions})
    top_recommendations = recommendations_df.sort_values('Predicted_Rating', ascending=False).head(num_recommendations)
    return top_recommendations.merge(books_df, on='ISBN')

# Database connection details
DATABASE = 'DBFinal2'
USERNAME = 'nz'
PASSWORD = '1q1q1q1q'
DRIVER = 'SQL Server'
SERVER = 'DESKTOP-2TE06S1\SQLEXPRESS02'

# Create connection
conn = pyodbc.connect(f'DRIVER={{SQL Server}};SERVER={SERVER};DATABASE={DATABASE};UID={USERNAME};PWD={PASSWORD}')

# Table names in the database
books_table = 'Books'
ratings_table = 'Ratings'
users_table = 'Users'

books_df, ratings_df, users_df = load_data(conn, books_table, ratings_table, users_table)

ratings_df = filter_data(ratings_df, books_df, users_df)

# Train or load model
model_path = 'svd_model.pkl'
if os.path.exists(model_path):
    with open(model_path, 'rb') as f:
        model = pickle.load(f)
else:
    model = train_model(ratings_df)

# Recommend books for a user
user_id = 9083
recommended_books = recommend_books(user_id, model, books_df, ratings_df)
print(recommended_books['ISBN'])