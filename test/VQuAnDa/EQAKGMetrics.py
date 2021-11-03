import requests
import json
import enchant
import csv
import re
import time
import itertools
from sacrebleu import sentence_bleu
import multiprocessing as mp
import os
import pandas as pd

def jsonToDict(route) -> dict:
    '''
    Funcion auxiliar que dada la ruta de un json, lo abre y lo convierte a diccionario
    '''
    with open(route, encoding="utf-8") as f:
        return json.load(f)

def queryJSON(queryURL, json):
    '''
    Funcion auxiliar que dado un JSON con una pregunta, realiza una consulta (con esta pregunta) a una URL
    '''
    question = json['question']
    files = {
        'question': (None, question),
    }
    '''
    En caso de que quisiesemos la respuesta verbalizada o larga, hacer la request con params = payload:
    payload = {
        ('text', 'true')
    }
    '''
    response = requests.get(queryURL, files = files)
    #Obtenemos la respuesta como JSonObject y la devolvemos
    return response.json()

def exactMatchScore(string1,string2):
    '''
    Funcion auxiliar que incorpora la medida EM (exact match)
    '''
    matches = 0
    total = 0
    for (x,y) in itertools.zip_longest(string1,string2):
        if(x == y):
            matches+=1
        total+=1
    return matches/total

def writeResults(csvRoute, rows, counter, question, modelAnswerLong, obtainedAnswer, queryTime, textLen):  
    '''
    Funcion auxiliar que extrae la respuesta que se espera, hace la distancia de levenshtein y añade a la lista de filas:
    -Pregunta
    -Respuesta modelo y nuestra respuesta
    -Distancia de levenshtein entre ambas respuestas
    -Tiempo que ha tardado en ejecutarse la consulta
    -Longitud del texto del que se ha obtenido nuestra respuesta
    -Si la pregunta dada tiene respuesta modelo o no
    '''    
    #La respuesta esperada se obtiene con una expresion regular (sacar texto entre corchetes)
    modelAnswerLongGroups = re.search(r"\[([^\)]+)\]", modelAnswerLong)
    if(modelAnswerLongGroups is not None):
        modelAnswer = modelAnswerLongGroups.group(1)
        isAnswered = "YES"
        if modelAnswer == "answer":
            isAnswered = "NO" 
        distance = "None"
        if obtainedAnswer is not None:
            distance = enchant.utils.levenshtein(modelAnswer,obtainedAnswer)
            reference = modelAnswer.split()
            candidate = obtainedAnswer.split()

            rows.append( [question, modelAnswer, obtainedAnswer, distance, sentence_bleu(obtainedAnswer,[modelAnswer]).score, exactMatchScore(reference,candidate), queryTime, textLen, isAnswered] )
            counter.value += 1
            #print("Contador: ", counter.value)

            #Escribimos cuando el valor del contador llegue a 24
            if(counter.value != 0 and counter.value % 24 == 0):
                #print("Escribiendo. Contador: ", counter.value)
                with open(csvRoute, 'a', newline='', encoding="utf-8") as f:
                    (pd.DataFrame.from_records(rows, columns=header)).to_csv(f, header=False, index=False, sep=';', quoting=csv.QUOTE_ALL)
                    rows[:] = []
                    f.close()


def evaluateQuestion(csvRoute, i, rows, counter, queryURL):
    '''
    Funcion auxiliar para paralelizar la ejecucion de consultas y escritura en csv de resultados. Realiza la consulta (midiendo el tiempo que tarda) y llama a writeResults
    '''
    #print("Process id: ", os.getpid())
    #print("Question: ", i['question']) 
    #Para medir el tiempo que se tarda en ejecutar la consulta
    queryStartTime = time.time()
    jsonResponse = queryJSON(queryURL,i)
    queryTime = round((time.time() - queryStartTime),2)

    #Pasamos las respuestas a minuscula y llamamos a extractAndCompare.
    writeResults(csvRoute, rows, counter, i['question'], i['verbalized_answer'].lower(),jsonResponse['answer'].lower(),queryTime,jsonResponse['textLen'])

def EQAKGMetrics(pool, rows, counter, JSONroute, queryURL, csvRoute):
    '''
    Funcion que dado un JSON con preguntas y respuestas (asumimos que las preguntas están en la clave 'question' del JSON, y las respuestas en 'verbalized_answers'), 
    una url a través de la cual realizar consultas y un csv donde guardar los resultados, hace una serie de metricas:
    - Realiza las preguntas del JSON dado
    - Lo compara con la respuesta esperada y obtiene varias metricas de rendimiento (Distancia de Levenshtein, BLEU, EM,...)
    - Escribe en el CSV la pregunta, la respuesta esperada, la respuesta obtenida y estas metricas
    '''
    VQuandaData = jsonToDict(JSONroute)

    #Escribimos el Header
    with open(csvRoute,'w', newline='', encoding="utf-8") as f:

        csvwriter = csv.writer(f,delimiter=';', quotechar='"', quoting=csv.QUOTE_ALL)
        global header
        csvwriter.writerow(header)
        f.close()
        
    for i in VQuandaData:
        #Paraleliza con metodos asincronos
        pool.apply_async(evaluateQuestion, (csvRoute,i,rows,counter,queryURL))

    pool.close()
    pool.join()

    #Escribimos lo que quede
    with open(csvRoute, 'a', newline='', encoding="utf-8") as f:
        (pd.DataFrame.from_records(rows, columns=header)).to_csv(f,header=False, sep=';', quoting=csv.QUOTE_ALL)
        f.close()

#Creamos el array donde guardaremos las columnas y el contador como variables globales para que sean accesibles por los multiprocesos
rows = None
counter = None
header = ["Question", "Answer", "Response", "Levenshtein Distance","BLEU Score","EM Score","Query Time","Text Length","Is Answered"]

if __name__ == '__main__':

    with mp.Manager() as manager:

        rows = manager.list([])
        counter = manager.Value('i', 0)

        pool = mp.Pool(processes=6, initargs = (counter,rows,))

        queryUrl = "http://localhost:5000/eqakg/dbpedia/en?text=false"
        #queryUrl = "https://librairy.linkeddata.es/eqakg/dbpedia/en?text=false" 

        EQAKGMetrics(pool,rows,counter,"test.json",queryUrl,"results/VQuanda.csv")