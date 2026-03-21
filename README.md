# ONCards
Elevate your learning experience.

<img width="1280" height="720" alt="Untitled" src="https://github.com/user-attachments/assets/ef66e9e1-5729-424d-898e-691a490336b0" />



**Recomended Requirements (For an "okay" experience):**
- i3 6100
- 16GB DDR3
- GTX 1070

# What is ONCards?
 **ONCards — Opensource Neural-accellerated Cards**
A fully offline study app with a virtual teacher and an algorithm which learns you as you go for better context and teach you better as you keep using the app.
 <img width="2559" height="1439" alt="image" src="https://github.com/user-attachments/assets/6115c89a-2c6f-42ac-951b-39721495b1db" />

**How to use it:**
- When the user opens the app, they will see the "create" tab.
- You can write your question (from your notes or slides)
- AI will complete the rest for you: title, hints, answer, difficulty, even the question location (eg: something related to "python language" will go to the "...\computer science\languages\Python..." path.
- you can go over to the "Cards" tab and press "Start" or click on a card to start studying your subject. Make sure to be on the correct subject path when you want to study a specific subject.
- You can write your answer (or reveal a hint if you are not sure)
- Press "grade" to see a virtual teacher grading your answer in real time.
- if you want help, just type a follow-up question and press enter for the teacher to explain it to you.

**Features for the next update:**
> I have being researching on implementing some usefull features and **trying to reduce the file size of the app** since the app is too large.

_important_
- Files To Card (TFC): FTC will allow you to import PNGs (school notes), Slides(.PPTX) from your teacher, or even PDFs which contains academic questions, then select how much question you want to make (max: 28Q/ 17pg-F). This is usefull since a student wont have time to manually write the questions in the creator. (Max files: 12 with max settings, 17 with max settings + force. minimum specs: GTX 1080 ti/ RTX 2060 super)
- Neural Algorithm (NNA): Right now, your next question is decided through a random selection from the sequence. With NNA, the study tab will give you test samples and then build the perfect set of cards from the neural network. This algorithm uses: a LLM, an embedding model, heuristics.
- Discuss: This is a generic AI assistant, but tuned to hellp you with studies. The reason for adding this feature is, the user can tag a card to the chat and ask about it. And most importantly the model has three levels of context awareness:
 Global awarenes – Name, Age, etc. (Predefined user data utilized by the application to ensure AI-generated content is appropriate for the user's age group.)
 Self Attention — The short form context the AI hold to remember the information in the chat.
 Long Term Short Memories (LTSM): AI will know more about you the more you speak with it. over time, it will feel more "personal" and understand you better.
- Memories: When you chat with the AI, it will save your strengths, weakneses, personality, hobbies to later feel more personalized. (Not related to LTSM)

_minor_
- enhanced UI: A better and intuitive UI is never a bad choice for a study app. right now, there is some bad engineering choices which will be removed and replaced with a better UI for better focus.
- Sound effects: Research says, "The more it feels responsive, the more you feel to interact". More studying? never a bad choice.

# Citation:
If you are using my code or elements from this project, please cite:
```
@MightyXdash/ONCard, 2026
https://github.com/MightyXdash/ONCard
```
Thanks for using my app🤗.
Love to the opensource community🥰.
