 ## Supported typehints
TODO

Separate the dep of chatbone and langgraph, so MessageInput only have content and role.
User use langgraph must manually compose langgraph message from message input and Context.
The role of datastore message should be general string, not Literal



1. List[Image] | List[Video]: List of all images or list of all videos.
2. List[Image|Video]: List of mixing Image and Video. multiple file picker for each.
3. Messages: does not support user imput multi messages, only one message.
4. Messages support to load history from Redis,  
5. Highest level of Union ( a: Image|Video) become radio visible switch.
6. Union with Nonetype must be the highest Union, not support List[Image|None]
7. List[Selection] or List[Status]  is invalid. 
8. Not support container in container.
8. Saver should be another app that monitor the stream. also can be trigger by dev-user. (create DataManager deployment)
9. Datastore shoulbe be design to store all information of assistant data.
10. Ignore NoneType., check only is_required.

List[List[Image|Video]] ? Supported with add more , multiple-option-picker button.

What if desire input is multiple tuple of multiple data (List[List[...]])?

List[List[Image]|Video] ? add more button and radio.

## If type is a list, make add_more button, and let user choose option, 
all mediatype inside a list will be 1 option file picker. message will become textfield. If a list, recursion.
# Union will become radio + stack (visible).

-> If only type except Selection or status inside a list, all option is file picker.
-> If there is lists inside lists, 1 file picker for all type, and one more filepicker per list.

All support type:
List[AnyMediaObject|Message]|Selection.