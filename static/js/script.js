jQuery(function ($) {

    $(".sidebar-dropdown > a").click(function() {
  $(".sidebar-submenu").slideUp(200);
  if (
    $(this)
      .parent()
      .hasClass("active")
  ) {
    $(".sidebar-dropdown").removeClass("active");
    $(this)
      .parent()
      .removeClass("active");
  } else {
    $(".sidebar-dropdown").removeClass("active");
    $(this)
      .next(".sidebar-submenu")
      .slideDown(200);
    $(this)
      .parent()
      .addClass("active");
  }
});

$("#close-sidebar").click(function() {
  $(".page-wrapper").removeClass("toggled");
});
$("#show-sidebar").click(function() {
  $(".page-wrapper").addClass("toggled");
});


   
   
});
// ==============================
// GREATKART JAVASCRIPT
// ==============================


// Page loaded
document.addEventListener("DOMContentLoaded", function () {

    console.log("Greatkart loaded successfully");

});


// ==============================
// PRODUCT QUANTITY
// ==============================

function increaseQuantity() {

    let quantity = document.getElementById("quantity");

    if (quantity) {
        quantity.value = parseInt(quantity.value) + 1;
    }

}


function decreaseQuantity() {

    let quantity = document.getElementById("quantity");

    if (quantity && parseInt(quantity.value) > 1) {
        quantity.value = parseInt(quantity.value) - 1;
    }

}


function addToCart() {

    alert("Product added to cart!");

}

function addToWishlist() {

    alert("Product added to wishlist!");

}